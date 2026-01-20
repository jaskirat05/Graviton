# Chain Execution Edge Cases & Caching Strategy

## Overview
This document outlines all edge cases in the approval/regeneration system and our caching strategy for handling complex dependency graphs.

---

## Edge Cases

### 1. 💎 **Diamond Dependencies (Shared Descendants)**

**Scenario:**
```
    A
   / \
  B   C
   \ /
    D
```

**Issues:**
- D depends on BOTH B and C
- If we regenerate A, all children (B, C, D) must regenerate
- If we regenerate only B, D must wait for both B (new) and C (old)
- D should execute ONCE, not twice

**Solution:**
- Track all dependencies for each node
- D is "ready" only when ALL dependencies are resolved
- Cache dependency versions to determine if D needs regeneration

**Caching Strategy:**
```python
D is valid ONLY if:
  - D has been executed
  - ALL dependencies (B, C) haven't changed since D's last execution
  - D's parameters haven't changed
```

**Test Case:**
```yaml
steps:
  - id: A
    workflow: generate_base
  - id: B
    workflow: variant_1
    depends_on: [A]
  - id: C
    workflow: variant_2
    depends_on: [A]
  - id: D
    workflow: merge
    depends_on: [B, C]
    parameters:
      input_left: "{{ B.output.artifact }}"
      input_right: "{{ C.output.artifact }}"
```

Regeneration scenarios:
- Regenerate A → Subgraph: {A, B, C, D} (all regenerate)
- Regenerate B → Subgraph: {B, D} (D uses NEW B + CACHED C)
- Regenerate C → Subgraph: {C, D} (D uses CACHED B + NEW C)

---

### 2. 🌳 **Cross-Branch Dependencies**

**Scenario:**
```
A → B → D
A → C → E → F
     ↓
     D
```

**Issues:**
- D depends on B (same branch) and C (different branch)
- If we regenerate B, D needs NEW B + OLD C
- If we regenerate C, D needs OLD B + NEW C
- If we regenerate A, entire tree regenerates

**Solution:**
- Build complete dependency graph (not just tree)
- When regenerating, include ALL paths to shared nodes

**Caching Strategy:**
```python
When regenerating node X:
  descendants = get_all_descendants(X)
  for desc in descendants:
    if all_dependencies_in_subgraph(desc):
      # All inputs are being regenerated
      mark_for_execution(desc)
    else:
      # Some inputs are cached
      mark_for_execution_with_mixed_inputs(desc)
```

---

### 3. 🔄 **Partial Subgraph Overlap**

**Scenario:**
```
A → B → C → D
    ↓
    E → F
```

**Issues:**
- Regenerate B → Subgraph: {B, C, D, E, F}
- User approves all regenerated nodes
- Later, regenerate C → Subgraph: {C, D}
- Should D use cached result from B's regeneration or regenerate again?

**Solution:**
- Track execution versions per node
- Track which dependency versions each node was built from

**Caching Strategy:**
```python
class StepExecutionRecord:
    step_id: str
    execution_version: int
    dependency_versions: Dict[str, int]  # {dep_step_id: dep_version}
    timestamp: datetime

# D is valid if:
for dep_id in D.dependencies:
    if dep_id in current_subgraph:
        # Dependency is being regenerated - must regenerate D
        return False
    if cached_D.dependency_versions[dep_id] != current_versions[dep_id]:
        # Dependency changed since last D execution
        return False
return True  # Can use cached D
```

---

### 4. ⛓️ **Approval Chain Reactions**

**Scenario:**
```
A (approval) → B (approval) → C
```

**Issues:**
- User rejects A with new params
- A regenerates
- B must regenerate (depends on new A output)
- B requires approval again
- If user rejects B, C must also regenerate
- Could create infinite approval loops

**Solution:**
- Track approval depth/count per regeneration session
- Set max cascading approvals limit
- Provide "approve all downstream" option

**Implementation:**
```python
approval_config:
  max_cascading_approvals: 5  # Fail if more than 5 sequential approvals
  auto_approve_downstream: false  # If true, only first node needs approval
```

---

### 5. ❓ **Conditional Steps in Subgraph**

**Scenario:**
```yaml
steps:
  - id: A
    workflow: quality_check
  - id: B
    workflow: enhance
    depends_on: [A]
    condition: "{{ A.output.quality_score > 0.8 }}"
  - id: C
    workflow: finalize
    depends_on: [B]
```

**Issues:**
- Initial run: A.quality_score = 0.9 → B executes → C executes
- User rejects A, regenerates with different params
- New run: A.quality_score = 0.6 → B skipped
- C depends on B which no longer exists

**Solution:**
- Mark conditional steps as "skipped" with reason
- Downstream steps check if dependencies are satisfied
- Options:
  1. Fail downstream if dependency skipped
  2. Skip downstream cascadingly
  3. Allow fallback values

**Implementation:**
```python
class StepResult:
    status: str  # "completed", "failed", "skipped_condition", "skipped_dependency"
    skip_reason: Optional[str]

# In workflow execution:
if dependency.status.startswith("skipped"):
    if node.skip_on_missing_dependency:
        skip_node(node, reason=f"Dependency {dep_id} was skipped")
    else:
        fail_node(node, reason=f"Required dependency {dep_id} not available")
```

---

### 6. ⚡ **Approval Timeout During Regeneration**

**Scenario:**
```
A → B (timeout: 1h) → C → D
```

**Issues:**
- Regenerating from A
- B times out waiting for approval
- Should C and D still execute with rejected B?

**Solution:**
- Configure timeout behavior per step:
  - `stop_chain`: Stop entire chain execution
  - `auto_approve`: Continue with timed-out result
  - `auto_reject`: Fail this step, skip descendants

**Implementation:**
```yaml
approval:
  timeout_hours: 1
  timeout_action: auto_reject  # or auto_approve, stop_chain
```

---

### 7. 🔁 **Max Retries Exhausted in Subgraph**

**Scenario:**
```
A → B (max_retries: 2) → C
```

**Issues:**
- User rejects B three times
- Retries exhausted
- What happens to C?

**Current Behavior:**
- Raises exception, fails step

**Proposed Behavior:**
- Configurable failure handling:
  - `fail_step_only`: Mark B as failed, skip C
  - `fail_chain`: Stop entire chain
  - `use_last_attempt`: Continue with last rejected result (risky)

---

### 8. 📊 **Version Conflicts & History**

**Scenario:**
```
A(v1) → B(v1) → C(v1)
Regenerate A → A(v2) → B(v2) → C(v2)
Regenerate B → A(v2) → B(v3) → C(v3)
```

**Issues:**
- User wants to compare v1 vs v2 vs v3
- User wants to "revert" to v1
- Need complete audit trail

**Solution:**
- Store full version tree in database
- Track parent-child relationships between versions
- Support version rollback

**Database Schema:**
```sql
ALTER TABLE workflows ADD COLUMN execution_version INTEGER DEFAULT 1;
ALTER TABLE workflows ADD COLUMN parent_workflow_id INTEGER REFERENCES workflows(id);

ALTER TABLE artifacts ADD COLUMN version INTEGER DEFAULT 1;
ALTER TABLE artifacts ADD COLUMN superseded_by_artifact_id INTEGER;
ALTER TABLE artifacts ADD COLUMN supersedes_artifact_id INTEGER;
```

---

### 9. 🔀 **Concurrent Regenerations**

**Scenario:**
```
A → B → C
```

**Issues:**
- User triggers regeneration of B
- While B is regenerating, user also triggers regeneration of A
- Now have two overlapping regeneration subgraphs

**Solution:**
- Lock mechanism for active regenerations
- Queue regeneration requests
- Cancel in-progress regenerations if parent node regenerated

**Implementation:**
```python
class ChainExecutionState:
    active_regenerations: Set[str]  # Set of step_ids currently regenerating
    regeneration_lock: asyncio.Lock

    async def regenerate_node(self, step_id: str):
        async with self.regeneration_lock:
            # Check if any ancestors are regenerating
            if any(anc in self.active_regenerations for anc in get_ancestors(step_id)):
                raise ConflictError("Ancestor regeneration in progress")

            self.active_regenerations.add(step_id)
            try:
                await execute_subgraph(step_id)
            finally:
                self.active_regenerations.remove(step_id)
```

---

## Caching Strategy Summary

### When to Use Cached Results

A node N can use cached results if ALL of the following are true:

1. ✅ **N has been executed before** (has StepResult)
2. ✅ **N is not in current regeneration subgraph**
3. ✅ **ALL dependencies have same version** as when N was last executed
4. ✅ **N's parameters haven't changed**
5. ✅ **N's condition (if any) still evaluates to true**

### Cache Invalidation Rules

Invalidate cached result for node N if:

1. ❌ **N is in regeneration subgraph** (explicit regeneration)
2. ❌ **Any dependency has higher version** than N was built with
3. ❌ **Parameters changed** (from approval rejection)
4. ❌ **Condition evaluation changed** (dependency output changed)
5. ❌ **Manual invalidation** (user request)

### Version Tracking

```python
class NodeExecutionState:
    step_id: str
    execution_version: int  # Increments with each execution
    dependency_snapshot: Dict[str, int]  # {dep_id: dep_version} at execution time
    parameter_hash: str  # Hash of resolved parameters
    executed_at: datetime

def is_cache_valid(node: NodeExecutionState, current_state: Dict[str, NodeExecutionState]) -> bool:
    """Check if cached node is still valid"""
    for dep_id, dep_version in node.dependency_snapshot.items():
        if current_state[dep_id].execution_version > dep_version:
            return False
    return True
```

---

## Priority Ranking

**High Priority (Must Handle):**
1. Diamond Dependencies (#1)
2. Conditional Steps (#5)
3. Partial Subgraph Overlap (#3)

**Medium Priority (Should Handle):**
4. Cross-Branch Dependencies (#2)
5. Approval Timeouts (#6)
6. Max Retries Exhausted (#7)
7. Version History (#8)

**Low Priority (Nice to Have):**
8. Approval Chain Reactions (#4)
9. Concurrent Regenerations (#9)

---

## Implementation Checklist

- [x] Implement `get_descendants()` using NetworkX (in ExecutionGraph)
- [x] Implement `get_ancestors()` using NetworkX (in ExecutionGraph)
- [x] Implement `create_subgraph()` for regeneration (in ExecutionGraph)
- [ ] Add `execution_version` tracking to StepNode
- [ ] Add `dependency_snapshot` to track dependency versions
- [ ] Implement cache validation logic
- [ ] Add conditional skip handling (skipped_condition, skipped_dependency)
- [ ] Database schema for version tracking
- [ ] Concurrent regeneration locks (using Temporal signals)
- [ ] Comprehensive test suite for each edge case

## Simplifications (Current Implementation)

**Single Output Per Step:**
- Each workflow produces exactly ONE artifact
- StepNode has `artifact_id: Optional[int]` (single value, not list)
- StepResult references single artifact via `artifact_id`
- Template references: `{{ step_id.output.image }}` or `{{ step_id.output.video }}`
- Future extension possible to support multiple outputs
