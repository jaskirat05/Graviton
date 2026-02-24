"""Registry service API (event-driven foundation)."""

from __future__ import annotations

import asyncio
import copy
import time
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect

from core.clients.comfy.http import ComfyHTTPClient
from core.logging_config import get_logger

from .config import settings
from .consumers import (
    bootstrap_server_health_ping_loops,
    close_control_plane_temporal_client,
    consume_control_plane_settings_updated,
    consume_data_plane_mode_updated,
    consume_server_registered,
    consume_server_registered_apply_data_plane_mode,
    consume_server_registered_health_ping,
    consume_server_registered_object_info,
    stop_server_health_ping_loops,
    consume_template_overrides_upserted,
    consume_template_overrides_upserted_node_definitions,
    consume_template_workflow_upserted,
)
from .health import HealthEvaluator
from .jetstream_bus import JetStreamEventBus
from .models import (
    ControlPlaneSettingsResponse,
    ServerControlPlaneStatusResponse,
    ControlPlaneSyncRequest,
    DataPlaneModeRequest,
    HealthResponse,
    PingRequest,
    RegisterWorkerSecretRequest,
    ServerResponse,
    ServerUpsertRequest,
    TemplateApplyOverridesRequest,
    TemplateRevalidateRequest,
    TemplateOverridesPatchRequest,
    TemplateOverridesRequest,
    TemplateWorkflowRequest,
    WorkerConfigPushJobResponse,
    WorkerControlSecretMetaResponse,
    WorkerControlSecretResponse,
)
from .node_definitions import (
    InMemoryNodeDefinitionsProjection,
    NodeDefinitionParameterPatchRequest,
    NodeDefinitionParametersReplaceRequest,
    NodeDefinitionsService,
)
from .projection import ProjectionStore
from .realtime import RegistryEventHub
from .service import RegistryService
from .template_manager import TemplateManager
from .template_store import TemplateStore

app = FastAPI(title="Registry Service", version=settings.service_version)
logger = get_logger("registry_service.main")

_bus = JetStreamEventBus()
_store = ProjectionStore()
_health_evaluator = HealthEvaluator(_store)
_template_store = TemplateStore()
_node_definition_projection = InMemoryNodeDefinitionsProjection()
_node_definitions = NodeDefinitionsService(_template_store, _node_definition_projection)
_template_manager = TemplateManager(_template_store, _store)
_event_hub = RegistryEventHub()
_service = RegistryService(
    _bus, _store, _health_evaluator, _template_store, _template_manager
)
_consumer_tasks: list[asyncio.Task] = []


def _server_url(server: dict) -> str:
    address = server["address"]
    port = server.get("port")
    ssl = bool(server.get("ssl", False))

    if address.startswith(("http://", "https://")):
        base = address.rstrip("/")
    else:
        scheme = "https" if ssl else "http"
        base = f"{scheme}://{address}"

    host_part = base.split("//", 1)[1]
    if port and ":" not in host_part:
        base = f"{base}:{port}"
    return base


def _get_combo_options_from_object_info(object_info: dict, class_type: str, input_name: str):
    node_info = object_info.get(class_type)
    if not node_info:
        return None
    input_types = node_info.get("input", {})
    for category in ["required", "optional"]:
        inputs = input_types.get(category, {})
        if input_name in inputs:
            input_def = inputs[input_name]
            if isinstance(input_def, list) and len(input_def) > 0:
                options = input_def[0]
                if isinstance(options, list):
                    return options
    return None


@app.on_event("startup")
async def startup() -> None:
    await _store.connect()
    await _bus.connect()
    projected = _node_definitions.bootstrap_from_templates()
    logger.info("registry_service_started", event_bus="nats-jetstream")
    logger.info("node_definition_projection_bootstrapped", count=projected)
    _consumer_tasks.append(
        asyncio.create_task(consume_server_registered(_bus, _service))
    )
    _consumer_tasks.append(
        asyncio.create_task(consume_server_registered_health_ping(_bus, _service, _event_hub))
    )
    _consumer_tasks.append(
        asyncio.create_task(consume_server_registered_object_info(_bus, _service))
    )
    _consumer_tasks.append(
        asyncio.create_task(consume_server_registered_apply_data_plane_mode(_bus, _service))
    )
    _consumer_tasks.append(
        asyncio.create_task(consume_template_workflow_upserted(_bus, _service))
    )
    _consumer_tasks.append(
        asyncio.create_task(consume_template_overrides_upserted(_bus, _service))
    )
    _consumer_tasks.append(
        asyncio.create_task(
            consume_template_overrides_upserted_node_definitions(
                _bus, _node_definitions, _event_hub
            )
        )
    )
    _consumer_tasks.append(
        asyncio.create_task(consume_data_plane_mode_updated(_bus, _service))
    )
    _consumer_tasks.append(
        asyncio.create_task(consume_control_plane_settings_updated(_bus, _service))
    )
    await bootstrap_server_health_ping_loops(_service, _event_hub)
    await asyncio.sleep(0.1)
    await _service.read_control_plane_settings(publish_event=True, force=False)


@app.on_event("shutdown")
async def shutdown() -> None:
    for task in _consumer_tasks:
        task.cancel()
    await stop_server_health_ping_loops()
    await close_control_plane_temporal_client()
    await _bus.close()
    await _store.close()


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.service_version,
        "event_bus": "nats-jetstream",
    }


@app.post("/v1/servers", response_model=ServerResponse)
async def upsert_server(request: ServerUpsertRequest) -> ServerResponse:
    try:
        result = await _service.upsert_server(request.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ServerResponse(**result)


@app.get("/v1/servers")
async def list_servers() -> dict:
    return await _service.list_servers()


@app.post("/v1/servers/{server_id}/control-secret", response_model=WorkerControlSecretResponse)
async def register_worker_control_secret(
    server_id: str,
    request: RegisterWorkerSecretRequest,
) -> WorkerControlSecretResponse:
    try:
        result = await _service.register_worker_control_secret(
            server_id=server_id,
            rotate=request.rotate,
        )
        return WorkerControlSecretResponse(**result)
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)


@app.get(
    "/v1/servers/{server_id}/control-secret/meta",
    response_model=WorkerControlSecretMetaResponse,
)
async def get_worker_control_secret_meta(server_id: str) -> WorkerControlSecretMetaResponse:
    try:
        result = await _service.get_worker_control_secret_meta(server_id)
        return WorkerControlSecretMetaResponse(**result)
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)


@app.post("/v1/servers/{server_id}:sync-workflows")
async def sync_server_workflows(server_id: str, force: bool = False) -> dict:
    try:
        return await _service.sync_server_templates(server_id, force=force)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/v1/servers/{server_id}:sync-object-info")
async def sync_server_object_info(server_id: str) -> dict:
    try:
        return await _service.refresh_server_object_info(server_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to sync object_info: {e}")


@app.post("/v1/dataplane/mode")
async def update_data_plane_mode(request: DataPlaneModeRequest) -> dict:
    try:
        result = await _service.update_data_plane_mode(request.mode)
        await _event_hub.broadcast({"type": "dataplane_mode_updated", "mode": result["mode"]})
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/v1/control-plane/settings", response_model=ControlPlaneSettingsResponse)
async def get_control_plane_settings() -> ControlPlaneSettingsResponse:
    result = await _service.get_control_plane_settings()
    return ControlPlaneSettingsResponse(**result)


@app.post("/v1/control-plane/sync")
async def trigger_control_plane_sync(request: ControlPlaneSyncRequest) -> dict:
    result = await _service.trigger_control_plane_sync(force=request.force)
    await _event_hub.broadcast(
        {
            "type": "control_plane_sync_triggered",
            "settings_hash": result.get("settings_hash"),
            "event_published": result.get("event_published", False),
            "settings_changed": result.get("settings_changed", False),
            "forced": request.force,
        }
    )
    return result


@app.post("/v1/servers/{server_id}:sync-dataplane")
async def trigger_server_control_plane_sync(
    server_id: str,
    request: ControlPlaneSyncRequest,
) -> dict:
    try:
        result = await _service.trigger_server_control_plane_sync(
            server_id=server_id,
            force=request.force,
        )
        await _event_hub.broadcast(
            {
                "type": "server_control_plane_sync_triggered",
                "server_id": server_id,
                "settings_hash": result.get("settings_hash"),
                "event_published": result.get("event_published", False),
                "forced": request.force,
            }
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get(
    "/v1/servers/{server_id}/control-plane-status",
    response_model=ServerControlPlaneStatusResponse,
)
async def get_server_control_plane_status(server_id: str) -> ServerControlPlaneStatusResponse:
    try:
        result = await _service.get_server_control_plane_status(server_id)
        return ServerControlPlaneStatusResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/v1/control-plane/push-jobs", response_model=list[WorkerConfigPushJobResponse])
async def list_control_plane_push_jobs(
    server_id: str | None = None,
    limit: int = 100,
) -> list[WorkerConfigPushJobResponse]:
    result = await _service.list_worker_config_push_jobs(server_id=server_id, limit=limit)
    return [WorkerConfigPushJobResponse(**job) for job in result["jobs"]]


@app.get("/v1/servers/{server_id}/object-info")
async def get_server_object_info(server_id: str, include_full: bool = False) -> dict:
    try:
        return await _service.get_server_object_info(server_id, include_full=include_full)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/v1/servers/{server_id}")
async def delete_server(server_id: str) -> dict:
    try:
        return await _service.delete_server(server_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/v1/servers/{server_id}/pings", response_model=HealthResponse)
async def ingest_ping(server_id: str, request: PingRequest) -> HealthResponse:
    if await _store.get_server(server_id) is None:
        raise HTTPException(status_code=404, detail=f"Server not found: {server_id}")

    result = await _service.ingest_ping(server_id, request.model_dump())
    return HealthResponse(**result)


@app.get("/v1/servers/{server_id}/health", response_model=HealthResponse)
async def get_server_health(server_id: str) -> HealthResponse:
    try:
        result = await _service.get_server_health(server_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return HealthResponse(**result)


@app.get("/v1/health/eligible")
async def get_eligible_servers() -> dict:
    return await _service.get_eligible_servers()


@app.websocket("/v1/events/ws")
async def registry_events_ws(websocket: WebSocket) -> None:
    await _event_hub.connect(websocket)
    try:
        await websocket.send_json({"type": "connected", "ts": int(time.time() * 1000)})
        while True:
            # Keepalive/read loop; we currently ignore client messages.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await _event_hub.disconnect(websocket)


@app.get("/v1/templates")
async def list_templates() -> dict:
    templates = _template_store.list_templates()
    return {"templates": templates, "count": len(templates)}


@app.get("/v1/node-definitions")
async def list_node_definitions() -> list[dict]:
    return _node_definitions.list_node_definitions()


@app.get("/v1/node-definitions/{workflow_name}")
async def get_node_definition(workflow_name: str) -> dict:
    try:
        return _node_definitions.get_node_definition(workflow_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.put("/v1/node-definitions/{workflow_name}/parameters")
async def replace_node_definition_parameters(
    workflow_name: str,
    request: NodeDefinitionParametersReplaceRequest,
) -> dict:
    overrides = _node_definitions.build_overrides_for_replace(
        workflow_name, request.parameters
    )
    try:
        await _service.upsert_template_overrides(workflow_name, overrides)
        _node_definitions.refresh_projection(workflow_name)
        return _node_definitions.get_node_definition(workflow_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.patch("/v1/node-definitions/{workflow_name}/parameters")
async def patch_node_definition_parameters(
    workflow_name: str,
    request: NodeDefinitionParameterPatchRequest,
) -> dict:
    overrides = _node_definitions.build_overrides_for_patch(
        workflow_name=workflow_name,
        upserts=request.upserts,
        remove_keys=request.remove_keys,
    )
    try:
        await _service.upsert_template_overrides(workflow_name, overrides)
        _node_definitions.refresh_projection(workflow_name)
        return _node_definitions.get_node_definition(workflow_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/v1/node-definitions/{workflow_name}/parameters/{parameter_key}")
async def delete_node_definition_parameter(workflow_name: str, parameter_key: str) -> dict:
    overrides = _node_definitions.build_overrides_for_patch(
        workflow_name=workflow_name,
        upserts=[],
        remove_keys=[parameter_key],
    )
    try:
        await _service.upsert_template_overrides(workflow_name, overrides)
        _node_definitions.refresh_projection(workflow_name)
        return _node_definitions.get_node_definition(workflow_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/v1/templates/{template_name}/workflow")
async def upsert_template_workflow(
    template_name: str, request: TemplateWorkflowRequest
) -> dict:
    try:
        result = await _service.upsert_template_workflow(template_name, request.workflow, force=True)
        await _event_hub.broadcast({"type": "template_changed", "template_name": template_name})
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/v1/templates/{template_name}:revalidate")
async def revalidate_template_workflow(
    template_name: str, request: TemplateRevalidateRequest
) -> dict:
    try:
        result = await _service.upsert_template_workflow(template_name, request.workflow, force=True)
        # Ensure node definitions update immediately for edit/save UX.
        await _service.generate_template_overrides(template_name)
        _node_definitions.refresh_projection(template_name)

        if result.get("status") == "active":
            await _service.refresh_validated_servers(template_name)
            _node_definitions.refresh_projection(template_name)

        node_definition = _node_definitions.get_node_definition(template_name)
        await _event_hub.broadcast({"type": "template_changed", "template_name": template_name})
        return {
            "template_name": template_name,
            "status": result.get("status", "active"),
            "policy_errors": result.get("policy_errors", []),
            "promoted": result.get("status") == "active",
            "node_definition": node_definition,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/v1/templates/{template_name}/overrides")
async def upsert_template_overrides(
    template_name: str, request: TemplateOverridesRequest
) -> dict:
    try:
        result = await _service.upsert_template_overrides(template_name, request.overrides)
        await _event_hub.broadcast({"type": "template_changed", "template_name": template_name})
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.patch("/v1/templates/{template_name}/overrides")
async def patch_template_overrides(
    template_name: str, request: TemplateOverridesPatchRequest
) -> dict:
    try:
        result = await _service.patch_template_overrides(
            template_name,
            upserts=request.upserts,
            remove_keys=request.remove_keys,
        )
        await _event_hub.broadcast({"type": "template_changed", "template_name": template_name})
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/v1/templates/{template_name}:generate-overrides")
async def generate_template_overrides(template_name: str) -> dict:
    try:
        result = await _service.generate_template_overrides(template_name)
        await _event_hub.broadcast({"type": "template_changed", "template_name": template_name})
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/v1/templates/{template_name}:apply-overrides")
async def apply_template_overrides(
    template_name: str, request: TemplateApplyOverridesRequest
) -> dict:
    try:
        return await _service.apply_template_overrides(
            template_name, request.runtime_overrides
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/v1/templates/{template_name}")
async def delete_template(template_name: str) -> dict:
    result = await _service.delete_template(template_name)
    _node_definitions.delete_node_definition(template_name)
    await _event_hub.broadcast({"type": "template_changed", "template_name": template_name})
    return result


@app.get("/v1/templates/{template_name}/workflow")
async def get_template_workflow(template_name: str) -> dict:
    try:
        workflow = _template_store.get_workflow(template_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Template workflow not found: {template_name}")
    return {"template_name": template_name, "workflow": workflow}


@app.get("/v1/templates/{template_name}/overrides")
async def get_template_overrides(template_name: str) -> dict:
    try:
        overrides = _template_store.get_overrides(template_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if overrides is None:
        raise HTTPException(status_code=404, detail=f"Template overrides not found: {template_name}")
    return {"template_name": template_name, "overrides": overrides}


@app.post("/v1/workflows/validate-server")
async def validate_workflow_server(request: dict) -> dict:
    workflow_name = request.get("workflow_name")
    server_name = request.get("server_name")
    if not workflow_name or not server_name:
        raise HTTPException(status_code=400, detail="workflow_name and server_name are required")

    try:
        server = await _service.get_server_by_name(server_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    workflow = _template_store.get_workflow(workflow_name)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Template workflow not found: {workflow_name}")

    overrides = _template_store.get_overrides(workflow_name) or {}
    validated_servers = overrides.get("validated_servers", [])

    if server_name in validated_servers:
        return {
            "valid": True,
            "workflow_name": workflow_name,
            "server_name": server_name,
            "already_validated": True,
        }

    client = ComfyHTTPClient(_server_url(server))
    try:
        object_info = await client.get_object_info()
    except Exception as e:
        await client.close()
        raise HTTPException(status_code=400, detail=f"Failed to fetch object_info: {e}")
    await client.close()

    missing_nodes = []
    invalid_inputs = []
    prompt = {k: v for k, v in workflow.items() if not str(k).startswith("_")}
    for node_id, node_data in prompt.items():
        if not isinstance(node_data, dict):
            continue
        class_type = node_data.get("class_type")
        if not class_type:
            continue
        if class_type not in object_info:
            missing_nodes.append(class_type)
            continue
        for input_name, value in node_data.get("inputs", {}).items():
            if isinstance(value, list) or not isinstance(value, str):
                continue
            options = _get_combo_options_from_object_info(object_info, class_type, input_name)
            if options is not None and value not in options:
                invalid_inputs.append(
                    {
                        "node_id": node_id,
                        "class_type": class_type,
                        "input_name": input_name,
                        "value": value,
                        "available_count": len(options),
                    }
                )

    if not missing_nodes and not invalid_inputs:
        merged = copy.deepcopy(overrides)
        merged["validated_servers"] = sorted(set(validated_servers + [server_name]))
        _template_store.upsert_overrides(workflow_name, merged)
        return {
            "valid": True,
            "workflow_name": workflow_name,
            "server_name": server_name,
            "already_validated": False,
        }

    return {
        "valid": False,
        "workflow_name": workflow_name,
        "server_name": server_name,
        "already_validated": False,
        "missing_nodes": sorted(set(missing_nodes)),
        "invalid_inputs": invalid_inputs,
    }


@app.get("/v1/workflows/{workflow_name}/parameter-options/{server_name}")
async def get_workflow_parameter_options(workflow_name: str, server_name: str) -> dict:
    try:
        server = await _service.get_server_by_name(server_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    overrides = _template_store.get_overrides(workflow_name)
    if overrides is None:
        raise HTTPException(status_code=404, detail=f"Template overrides not found: {workflow_name}")

    client = ComfyHTTPClient(_server_url(server))
    try:
        object_info = await client.get_object_info()
    except Exception as e:
        await client.close()
        raise HTTPException(status_code=400, detail=f"Failed to fetch object_info: {e}")
    await client.close()

    parameter_options = {}
    for param in overrides.get("parameters", []):
        class_type = param.get("node_class")
        input_name = param.get("input_key")
        param_key = param.get("key")
        if not class_type or not input_name or not param_key:
            continue
        options = _get_combo_options_from_object_info(object_info, class_type, input_name)
        if options:
            parameter_options[param_key] = options

    return {
        "workflow_name": workflow_name,
        "server_name": server_name,
        "parameter_options": parameter_options,
        "count": len(parameter_options),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8010, log_level="info")
