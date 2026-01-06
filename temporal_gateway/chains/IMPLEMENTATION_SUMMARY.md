# Chain Execution Implementation Summary

## Architecture Overview

The chain execution system uses a **cancel-and-restart with cache** approach for handling rejections and regenerations.

### Core Principle

When a step is rejected:
1. **Complete the current level** (don't cancel parallel steps mid-execution)
2. **Build cache** from all successfully completed steps
3. **Spawn new chain** with cache + updated parameters for rejected step
4. **Mark current chain** as "partial" and exit

No complex parent-child merging. No in-memory versioning. Database is the source of truth.

---

## Key Components

### 1. ExecutionGraph (DAG with NetworkX)

**File:** `temporal_gateway/chains/models/execution_graph.py`

**Purpose:** Directed Acyclic Graph for managing step dependencies and execution

**Key Methods:**
- `get_descendants(step_id)` - Get all steps that depend on this step (for skip propagation)
- `get_ancestors(step_id)` - Get all dependencies of this step
- `get_execution_levels()` - Get parallel execution levels using topological sort
- `validate_dag()` - Ensure no circular dependencies
- `apply_cached_result(step_id, cached_result)` - Apply cache from database
- `propagate_skip(step_id)` - Mark all descendants as skipped
- `build_step_result_from_node(step_id)` - Extract result from completed node

**NetworkX Usage:**
```python
# Add nodes and edges
graph.add_node(step_id, node=StepNode(...))
graph.add_edge(dep_id, step_id)  # dep_id → step_id

# Get descendants (for skip propagation)
descendants = nx.descendants(graph, step_id)

# Get parallel execution levels
levels = nx.topological_generations(graph)
# Example: [[A], [B, C], [D]] - A first, then B&C parallel, then D
```

### 2. Chain Versioning (Database)

**File:** `temporal_gateway/database/models.py`

**Schema:**
```python
class Chain:
    name: str  # "image-edit-pipeline"
    version: int  # 1, 2, 3...
    regenerated_from_step_id: str  # Which step triggered this version

    __table_args__ = (
        UniqueConstraint('name', 'version'),
        Index('idx_chain_name_status_version', 'name', 'status', 'version'),
    )
```

**Prevents:** Concurrent version conflicts with row-level locking

### 3. Cache Building (Database Queries)

**File:** `temporal_gateway/activities/cache_operations.py`

**Key Activities:**

```python
@activity.defn
async def build_cache_from_database(chain_name, exclude_step_id):
    """
    Query database for latest completed workflow per step
    - Checks if artifact still exists on disk
    - Returns dict mapping step_id to StepResult
    """

@activity.defn
async def get_next_chain_version(chain_name):
    """
    Get next version number with database lock
    - Uses with_for_update() to prevent conflicts
    """
```

**How it works:**
```sql
-- Get latest completed workflow for each step
SELECT * FROM workflows w
JOIN chains c ON w.chain_id = c.id
WHERE c.name = 'image-edit-pipeline'
  AND w.status = 'completed'
  AND w.step_id != 'excluded_step'
ORDER BY w.completed_at DESC
-- Then deduplicate by step_id to get latest per step
```

### 4. Workflow Execution (Level-by-Level)

**File:** `temporal_gateway/workflows/chain/workflow.py`

**Main Flow:**

```python
@workflow.run
async def run(request: ChainExecutionRequest):
    graph = request.graph
    cached_results = request.cached_results or {}
    retry_number = request.retry_number

    # Apply cache to graph
    for step_id, cached_result in cached_results.items():
        graph.apply_cached_result(step_id, cached_result)

    # Execute level by level
    for level_num, level_steps in enumerate(graph.get_execution_levels()):
        # Execute level, wait for all to complete
        level_results, rejected_step = await self._execute_level(graph, level_steps)

        # Check for rejection
        if rejected_step:
            # Build cache from current execution
            cache = await self._build_cache_for_retry(graph)

            # Spawn new chain
            await self._spawn_retry_chain(graph, rejected_step, cache, retry_number + 1)

            # Mark current chain as partial and exit
            return ChainExecutionResult(status="partial")

    return ChainExecutionResult(status="completed")
```

**_execute_level() - Wait-for-Completion Pattern:**

```python
async def _execute_level(graph, level_steps):
    """
    Execute steps in parallel, wait for ALL to complete
    """
    tasks = {}
    results = {}
    rejected_step = None

    for step_id in level_steps:
        node = graph.get_node(step_id)

        # Check if cached
        if node.status == "completed":
            results[step_id] = graph.build_step_result_from_node(step_id)
            continue

        # Check dependencies
        for dep_id in node.dependencies:
            if dep_node.status != "completed":
                # Dependency failed - skip this step
                node.mark_skipped_dependency(dep_id)
                results[step_id] = StepResult(status="skipped_dependency")
                continue

        # Schedule execution
        tasks[step_id] = self._execute_step(node)

    # Wait for ALL tasks
    task_results = await asyncio.gather(*tasks.values())

    # Check for rejection
    for step_id, result in zip(tasks.keys(), task_results):
        results[step_id] = result
        if result.approval_decision == "rejected":
            rejected_step = step_id

    return results, rejected_step
```

**Key Insight:** Even if step C is rejected at t=30s, we wait for parallel step B to finish at t=5min before handling the rejection. This preserves B's work!

**_build_cache_for_retry() - Extract from Current Execution:**

```python
async def _build_cache_for_retry(graph):
    """
    Extract completed steps from current execution
    """
    cache = {}
    for step_id, node in graph.nodes.items():
        if node.status == "completed" and node.artifact_id:
            cache[step_id] = {
                "step_id": step_id,
                "artifact_id": node.artifact_id,
                "workflow_db_id": node.workflow_db_id,
                # ...
            }
    return cache
```

**_spawn_retry_chain() - Start New Chain:**

```python
async def _spawn_retry_chain(graph, rejected_step, cache, retry_number):
    """
    Start new chain with cache
    """
    # Update rejected step params
    graph.update_step_with_new_parameters(rejected_step, new_params)

    # Create request
    retry_request = ChainExecutionRequest(
        graph=graph,
        cached_results=cache,
        retry_number=retry_number
    )

    # Start new workflow (fire and forget)
    await workflow.start_child_workflow(
        ChainExecutorWorkflow.run,
        args=[retry_request],
        id=f"{workflow_id}-retry-{retry_number}"
    )
```

---

## Execution Flow Example

### Chain Definition:
```yaml
name: image-edit-pipeline
steps:
  - id: A
    workflow: text_to_image
  - id: B
    workflow: enhance_image
    depends_on: [A]
  - id: C
    workflow: add_effects
    depends_on: [A]
    requires_approval: true  # ← Rejection point
  - id: D
    workflow: merge_images
    depends_on: [B, C]
```

### Execution Timeline:

**Chain v1 (Initial):**
```
t=0:   Chain v1 starts (workflow_id: chain-abc-123)
       Cache: {}

t=0:   Level 0: Execute A
       A completes ✓ (artifact_id: 100)

t=30:  Level 1: Execute B, C in parallel
       B starts (5 min job)
       C starts (30 sec job)

t=60:  C completes ✓ (artifact_id: 102)
       Approval requested

t=90:  User REJECTS C with new parameters

t=90:  _execute_level waits... (B still running)

t=330: B completes ✓ (artifact_id: 101)

t=330: _execute_level returns:
       results = {B: completed, C: completed}
       rejected_step = "C"

t=330: Build cache from v1:
       cache = {
         A: {artifact_id: 100},
         B: {artifact_id: 101}
       }

t=330: Spawn Chain v2:
       workflow_id: chain-abc-123-retry-1
       cached_results: {A, B}
       C updated with new parameters

t=330: Mark Chain v1 as "partial"
       Chain v1 exits
```

**Chain v2 (Retry):**
```
t=330: Chain v2 starts (workflow_id: chain-abc-123-retry-1)
       Cache: {A, B}

t=330: Apply cache:
       graph.nodes[A].status = "completed"
       graph.nodes[A].artifact_id = 100
       graph.nodes[B].status = "completed"
       graph.nodes[B].artifact_id = 101

t=330: Level 0: [A]
       A is cached → skip

t=330: Level 1: [B, C]
       B is cached → skip
       C not cached → execute with NEW params

t=360: C completes ✓ (artifact_id: 103)
       Approval requested
       User APPROVES ✓

t=360: Level 2: [D]
       Dependencies: B (cached), C (fresh)
       Transfer artifact 101 from B to server
       Transfer artifact 103 from C to server
       Execute D ✓

t=400: Chain v2 completes
       Status: "completed"
```

**Database State:**
```sql
-- Chains table
id          name                   version  status    regenerated_from_step_id
chain-v1    image-edit-pipeline    1        partial   NULL
chain-v2    image-edit-pipeline    2        completed C

-- Workflows table (simplified)
id    chain_id   step_id  status     artifact_id
w1    chain-v1   A        completed  100
w2    chain-v1   B        completed  101
w3    chain-v1   C        completed  102  (rejected)
w4    chain-v2   C        completed  103  (approved)
w5    chain-v2   D        completed  104
```

---

## Key Design Decisions

### 1. **Why Cancel-and-Restart vs Parent-Child?**

**Parent-Child (Rejected):**
- Complex state merging
- Two graphs with duplicate nodes
- Hard to track in Temporal UI

**Cancel-and-Restart (Chosen):**
- Simple: one chain at a time
- Clear audit trail (separate workflow IDs)
- Database queries get "latest" naturally
- Less code complexity

### 2. **Why No In-Memory Versioning?**

**No Need Because:**
- Each chain execution is independent
- Database stores all workflow results
- Cache builder queries database for "latest completed per step"
- No need to track dependency versions in memory

### 3. **Why Wait-for-Completion?**

**GPU Time is Expensive:**
- If B is 80% done when C is rejected, DON'T cancel B
- Wait for B to finish, cache it, use in retry chain
- Saves minutes of GPU re-computation

### 4. **Why Not Fail Immediately on Failure?**

**Parallel Branches Can Succeed:**
```
  A
 / \
B   C (fails)
|   |
D   E
```
If C fails, E still succeeds. We want E's output!

**Simple Logic:**
- Continue through all levels
- Steps check their dependencies
- Skip if dependency failed
- Get partial results

---

## Testing Checklist

- [ ] Linear chain (A → B → C)
- [ ] Parallel branches (A → [B, C] → D)
- [ ] Diamond dependencies (A → [B, C] → D where D depends on both)
- [ ] Rejection with parallel steps running
- [ ] Multiple rejections in same chain
- [ ] Conditional step skipping
- [ ] Dependency failure propagation
- [ ] Cache validation (artifact exists check)
- [ ] Concurrent chain version creation
- [ ] Database chain version uniqueness

---

## Performance Characteristics

**Cache Lookup:** O(steps) database query with index
**Level Execution:** O(max_parallel_steps) concurrent tasks
**Skip Propagation:** O(descendants) using NetworkX
**Graph Validation:** O(V + E) DAG check

**Typical Chain (5 steps, 3 levels):**
- Cache query: ~50ms
- Level execution: parallel (limited by slowest step)
- Total overhead: <1 second

---

## Future Enhancements

1. **Fail-Fast Option:** Skip remaining levels if critical path blocked
2. **Cache Expiry:** Invalidate cache older than N hours
3. **Manual Regeneration API:** User-triggered regeneration from specific step
4. **Branch Versioning:** Support experimental branches (main/v1, experiment/v1)
5. **Artifact Cleanup:** Retention policy for old chain versions
