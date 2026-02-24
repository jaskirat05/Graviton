# Registry Microservice Plan

## Context From Current Repo
- Server definitions are static in `config.yaml` under `servers`.
- Runtime services (`comfy-gateway`, `comfy-worker`) consume that config via mounted file + `CONFIG_PATH`.
- Template files and generated `_overrides.json` live in mounted `templates/`.
- Backend implementation is not present in this repo (pulled as container images), so this plan targets a clean external registry service with explicit contracts.

## Problems To Fix
- Registry concerns are coupled to static config + ad-hoc logic.
- Health is inferred indirectly; no durable server heartbeat/ping object model.
- Template override behavior exists, but ownership/lifecycle is unclear and likely spread across components.
- Difficult to evolve load balancing and validation without central source of truth.

## Target Outcomes
- A dedicated `registry-service` becomes source of truth for:
  - Server registration + metadata
  - Health status via ping objects and heartbeat processing
  - Template override definitions and inheritance
  - Query endpoints used by gateway/worker/scheduler
- Safe migration from file-driven config to API-driven registry.

## Service Boundaries
- Owns:
  - Server inventory and status
  - Ping object ingestion + health evaluation
  - Template override CRUD + versioning
  - Capability snapshots (optional first, required later)
- Does not own:
  - Workflow execution state (Temporal domain)
  - Artifact storage
  - UI orchestration logic

## Proposed Architecture
- New service: `registry-service` (HTTP API; optional async events).
- Data store: Postgres (reuse existing stack; separate schema/database).
- Cache: Redis optional for hot reads and short-lived heartbeat windows.
- Integrations:
  - `comfy-gateway`: read active servers, template override resolution.
  - `comfy-worker`: publish ping objects and capability snapshots.
  - Scheduler/load balancer: query healthy + eligible servers.

## Core Domain Model

### 1) Server Registry
- `server`
  - `id` (uuid)
  - `name` (unique, human-readable)
  - `provider` (e.g., `comfyui`)
  - `address`, `port`, `ssl`
  - `status` (`registered|draining|disabled|deleted`)
  - `tags` (jsonb)
  - `weight` (int, default 1)
  - `created_at`, `updated_at`

### 2) Ping Objects (Health)
- `server_ping`
  - `id` (uuid)
  - `server_id`
  - `reported_at` (from agent)
  - `received_at` (service timestamp)
  - `ok` (bool)
  - `latency_ms`
  - `queue_depth` (nullable)
  - `gpu_utilization` (nullable)
  - `vram_free_mb` (nullable)
  - `error_code`, `error_message` (nullable)
  - `raw_payload` (jsonb)
- Derived materialized view/table: `server_health`
  - `server_id`
  - `health_state` (`healthy|degraded|unhealthy|stale`)
  - `last_ok_at`, `last_seen_at`
  - `health_score` (0-100)
  - `reason`

### 3) Template Overrides
- `template`
  - `id` (uuid)
  - `name` (unique)
  - `version`
  - `base_hash` (source template fingerprint)
- `template_override_set`
  - `id` (uuid)
  - `template_id`
  - `scope_type` (`global|provider|server|team|project`)
  - `scope_ref` (nullable for global)
  - `priority` (int; higher wins)
  - `active` (bool)
  - `version`
- `template_override_entry`
  - `id` (uuid)
  - `override_set_id`
  - `json_path`
  - `value` (jsonb)
  - `op` (`replace|remove|append|merge`)

## Health Evaluation Policy (Initial)
- Heartbeat interval target: every 10s from worker/agent.
- Stale threshold: 30s without ping.
- Unhealthy threshold: 3 consecutive failed pings.
- Degraded when:
  - Latency above configurable threshold
  - Queue depth high
  - VRAM free below floor
- Eligibility for scheduling uses `server_health.health_state in (healthy, degraded)` + policy gates.

## API Surface (v1)

### Server APIs
- `POST /v1/servers` register/update by `name`
- `GET /v1/servers` list with filters (`provider`, `status`, `health_state`, tags)
- `GET /v1/servers/{id}`
- `PATCH /v1/servers/{id}` (drain/enable/disable, weight, tags)
- `DELETE /v1/servers/{id}` soft-delete

### Ping APIs
- `POST /v1/servers/{id}/pings` ingest ping object
- `GET /v1/servers/{id}/health` current evaluated health
- `GET /v1/health/eligible` scheduling-ready server list

### Template Override APIs
- `GET /v1/templates`
- `POST /v1/templates/{template_id}/override-sets`
- `PATCH /v1/override-sets/{id}`
- `POST /v1/override-sets/{id}/entries`
- `POST /v1/templates/{template_id}:resolve-overrides`
  - Input: scope context (`server_id`, `provider`, `team`, `project`)
  - Output: merged effective override document + resolution trace

## Security + Governance
- Service auth: internal token/JWT between gateway/worker and registry.
- RBAC:
  - Read-only consumers (scheduler, UI read paths)
  - Admin for server lifecycle + override mutations
- Audit log for:
  - Server status changes
  - Override set create/update/delete
  - Manual health overrides (if added)

## Observability
- Metrics:
  - ping ingest rate/errors
  - stale server count
  - health state distribution
  - override resolution latency/error rate
- Structured logs with `server_id`, `template_id`, `request_id`.
- Traces for ingest and resolve endpoints.

## Migration Plan

### Phase 0: Discovery + Contract Freeze (2-4 days)
- Inventory current registry-related behavior inside backend images/repo(s).
- Freeze initial API contracts and health semantics.
- Identify backward-compat requirements for `config.yaml` and existing templates.

### Phase 1: Read-Only Bootstrap (3-5 days)
- Stand up `registry-service` with schema + read APIs.
- Add config importer:
  - Import `config.yaml` `servers` into registry on startup or via job.
- Keep existing execution flow unchanged.

### Phase 2: Health Ingestion (4-7 days)
- Implement ping ingest endpoint + health evaluator.
- Update worker/agent to emit pings.
- Scheduler/gateway begins reading health from registry (feature flag).

### Phase 3: Template Override Ownership (5-8 days)
- Introduce override set schema and merge engine.
- Import existing `_overrides.json` into override sets.
- Gateway reads resolved overrides from registry (feature flag + fallback).

### Phase 4: Cutover + Decommission (3-5 days)
- Make registry authoritative for server list and overrides.
- Keep `config.yaml` only for bootstrap defaults or remove entirely.
- Remove legacy hack paths after stability window.

## Backward Compatibility Strategy
- Dual-read period:
  - Primary: registry
  - Fallback: current local config/templates behavior
- Feature flags:
  - `REGISTRY_READ_SERVERS_ENABLED`
  - `REGISTRY_HEALTH_ENABLED`
  - `REGISTRY_TEMPLATE_OVERRIDES_ENABLED`
- Rollback:
  - Toggle flags off to revert to legacy behavior.

## Delivery Checklist
- [ ] Finalize API spec (OpenAPI)
- [ ] DB migrations + indexes (server_id + timestamps)
- [ ] Health evaluator job/worker
- [ ] Override merge semantics test suite
- [ ] Gateway integration (server discovery + overrides)
- [ ] Worker integration (ping emitter)
- [ ] Dashboards + alerts
- [ ] Runbook for stale/unhealthy/draining states

## Risks and Mitigations
- Missing source visibility of current hacks.
  - Mitigation: extract behavior contracts from running services and logs before cutover.
- Health flapping under transient network spikes.
  - Mitigation: consecutive-failure windows + hysteresis for recovery.
- Override conflicts across scopes.
  - Mitigation: explicit priority rules + resolution trace in API response.

## Open Questions
- Should server registration be push-only (agents self-register) or mixed with admin-managed entries?
- Do we need multi-tenant isolation now (`team/project`) or after v1?
- Should health include active workflow load pulled from Temporal queues for better scheduling decisions?
- Who is the authority for template base versions (filesystem sync vs API upload)?
