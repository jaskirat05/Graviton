# Implementation Plan: Policy-First Templates + Invalid Bucket Workflow

## Objective

Implement a policy-first template lifecycle where:

- Templates that violate platform policy (especially multi-output) are marked invalid.
- Invalid templates are still visible as node definitions under a separate category.
- Users can edit invalid templates in ComfyUI frontend and save.
- Saved templates are revalidated; once policy-compliant, they are promoted for normal use.

## Product Constraints

- Keep the existing invariant: one workflow run maps to one canonical artifact in platform flows.
- A template is considered usable only if it passes:
  1. Platform policy checks.
  2. Server validation checks.
- Invalid templates must be discoverable in UI but not executable as normal nodes.

## Non-Goals (for this phase)

- Full multi-output execution support.
- Reworking chain runtime to support artifact arrays.
- Deep ComfyUI extension work beyond minimum integration points.

## High-Level Design

### 1. Policy-First Sync

On template ingest/sync:

1. Parse workflow.
2. Run platform policy validation first.
3. If policy fails:
   - Store template as invalid with policy errors.
   - Generate node definition in category `invalid`.
   - Skip normal validated-server refresh for active usage.
4. If policy passes:
   - Continue existing overrides generation + server validation.
   - Expose as normal node category.

### 2. Invalid Bucket

Represent invalid templates as first-class entities, not dropped rows.

State model:

- `active`
- `invalid_policy`
- `invalid_server`
- `draft` (optional intermediate for manual edits)

For this iteration, minimum required: `active` and `invalid_policy`.

### 3. Node Definition Exposure

Invalid templates should still be projected to node definitions with:

- `category = "invalid"`
- `is_invalid = true`
- `validation_errors = [...]`

UI uses this to:

- Show them in a separate category.
- Disable execute path.
- Keep “open in ComfyUI” + “save and revalidate” actions enabled.

### 4. Edit + Revalidate + Promote

Flow:

1. User opens invalid node in ComfyUI frontend (validated server as backend target).
2. User saves edited workflow.
3. Backend endpoint re-runs policy checks (and then server validation if policy passes).
4. If valid:
   - Promote to `active`.
   - Refresh overrides + node projection in normal category.
5. If still invalid:
   - Keep in invalid bucket.
   - Return actionable policy errors.

## Backend Changes

### A. Registry Policy Module

Create a policy checker module in `core/registry_service/`:

- `check_template_policy(template_name, workflow) -> PolicyResult`
- Include error codes:
  - `POLICY_MULTI_OUTPUT_UNSUPPORTED`
  - `POLICY_UNSUPPORTED_OUTPUT_TYPE`
  - `POLICY_TEMPLATE_NAME_INVALID`
  - `POLICY_MISSING_UI_METADATA` (optional strictness)

Initial rule strategy:

- Detect likely multiple terminal outputs and fail policy.
- Keep detection explicit and deterministic; avoid heuristic-only behavior where possible.

### B. Template Metadata Persistence

Extend storage model to persist template status metadata (new file or embedded metadata):

- `status`
- `policy_errors`
- `updated_at`
- `source_server` (optional)

Suggested approach for speed:

- Add `registry_templates/status/<template>.json` as sidecar metadata.
- Keep existing workflow and overrides files unchanged.

### C. Service Layer Integration

Update `RegistryService.upsert_template_workflow` and sync consumers:

- Run policy check before normal upsert flow.
- On policy fail:
  - Persist workflow + status metadata as invalid.
  - Ensure overrides/projection can still be built for node listing.
  - Return structured response with `skipped_active=true`.
- On policy pass:
  - Existing behavior.

### D. Validated Servers Refresh Guard

Update `refresh_validated_servers`:

- If template status is invalid policy, skip active server validation and return status-aware response.

### E. New Revalidate Endpoint

Add endpoint for edit-save callback:

- `POST /v1/templates/{template_name}:revalidate`
- Input: updated workflow JSON, optional server context.
- Output: status, category, errors, promotion result.

## Frontend Changes

### A. Node Category Support

Extend frontend category union:

- Add `invalid` to `NodeCategory`.
- Add visual style block in context menu and node chips.

### B. Invalid Node UX

For `invalid` nodes:

- Show warning badge and short reason.
- Disable execute action.
- Keep edit/open action available.

### C. ComfyUI Open Action

Add top-right arrow action on node:

- Picks user-selected server or first validated server.
- Opens ComfyUI frontend URL for that server.
- Passes workflow context for editing (initially via copy/paste fallback if auto-import bridge is unavailable).

### D. Save + Revalidate Action

After edit save, call `:revalidate` endpoint and refresh node definitions.

## API Contract Additions (Draft)

### Template Status in Node Definition

Node definition response additions:

- `status: "active" | "invalid_policy" | "invalid_server"`
- `is_invalid: boolean`
- `validation_errors: string[]`

### Revalidate Endpoint

Request:

```json
{
  "workflow": { "...": "..." },
  "server_name": "optional-server"
}
```

Response:

```json
{
  "template_name": "example",
  "status": "active",
  "category": "image",
  "policy_errors": [],
  "validated_servers": ["server-a"],
  "promoted": true
}
```

## Execution Plan (Phased)

### Phase 1: Backend Policy + Invalid Persistence

- Add policy module and error codes.
- Add status sidecar persistence.
- Integrate policy-first path into sync/upsert.

### Phase 2: Node Projection + API

- Emit invalid templates in node definitions (`category=invalid`).
- Add template status fields in API responses.
- Add revalidate endpoint.

### Phase 3: Frontend Invalid UX

- Add invalid category visuals.
- Disable execute for invalid nodes.
- Add arrow affordance and revalidate trigger.

### Phase 4: Hardening

- Add tests for policy-first branching and promotion transitions.
- Add logging/metrics for invalid counts and promotion success rates.

## Risks and Mitigations

1. Ambiguous multi-output detection
- Mitigation: start with explicit conservative detection and clear error text.

2. ComfyUI auto-import limitations
- Mitigation: support open + manual import fallback first, add bridge later.

3. State drift between workflow/overrides/status files
- Mitigation: centralize writes via service methods and keep updates transactional per operation.

## Acceptance Criteria

1. On sync, policy-invalid templates no longer break sync for other templates.
2. Policy-invalid templates appear in frontend under `invalid` category.
3. Invalid templates cannot be executed as normal nodes.
4. User can edit and save; backend revalidates.
5. After successful revalidation, template moves from `invalid` to normal category.
6. Existing active templates and one-artifact runtime behavior remain unchanged.

