"""
Approval Service

Handles approval operations including parameter validation and Temporal signaling.
"""

from typing import Dict, Any, List, Optional, Tuple
from temporalio.client import Client

from core.workflow_registry import get_registry
from core.database.crud.approval import (
    get_approval_request_by_token,
    approve_approval_request,
    reject_approval_request,
    validate_approval_link,
)
from core.database.session import get_session
from core.observability.chain_logger import ChainLogger


class ApprovalParameterValidator:
    """Validates parameters against workflow registry schema"""

    def __init__(self, workflow_registry=None):
        self.registry = workflow_registry or get_registry()

    def validate_parameters(
        self,
        workflow_name: str,
        provided_params: Dict[str, Any]
    ) -> Tuple[bool, List[str]]:
        """
        Validate provided parameters against workflow registry

        In the current workflow registry design:
        - All parameters in the override file are editable
        - Parameters NOT in override file are immutable (frozen)

        Args:
            workflow_name: Name of the workflow
            provided_params: Parameters provided for regeneration

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # Get workflow info from registry
        workflow_info = self.registry.get_workflow_info(workflow_name)
        if not workflow_info:
            errors.append(f"Workflow '{workflow_name}' not found in registry")
            return False, errors

        # Get parameter schema (all params in override file are editable)
        registered_params = workflow_info.get('parameters', [])

        # Build lookup dict: key -> parameter info
        param_lookup = {p['key']: p for p in registered_params}

        # Validate each provided parameter
        for param_key, param_value in provided_params.items():
            if param_key not in param_lookup:
                # Parameter not in override file = not editable
                errors.append(
                    f"Parameter '{param_key}' is not editable "
                    f"(not found in workflow override file)"
                )
                continue

            param_info = param_lookup[param_key]

            # Type validation
            expected_type = param_info['type']
            validation_error = self._validate_type(
                param_key,
                param_value,
                expected_type
            )
            if validation_error:
                errors.append(validation_error)

        is_valid = len(errors) == 0
        return is_valid, errors

    def _validate_type(
        self,
        param_key: str,
        value: Any,
        expected_type: str
    ) -> Optional[str]:
        """Validate parameter type"""

        # Map Python type names to validators
        type_validators = {
            'str': (str, "string"),
            'int': (int, "integer"),
            'float': ((int, float), "number"),
            'bool': (bool, "boolean"),
            'list': (list, "list"),
            'dict': (dict, "object"),
        }

        if expected_type not in type_validators:
            # Unknown type, skip validation
            return None

        expected_python_types, type_name = type_validators[expected_type]

        if not isinstance(value, expected_python_types):
            actual_type = type(value).__name__
            return (
                f"Parameter '{param_key}' must be a {type_name}, "
                f"got {actual_type}"
            )

        return None

    def get_editable_parameters(
        self,
        workflow_name: str
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get all editable parameters for a workflow

        Returns:
            List of parameter definitions, or None if workflow not found
        """
        workflow_info = self.registry.get_workflow_info(workflow_name)
        if not workflow_info:
            return None

        # All parameters in registry are editable (from override file)
        return workflow_info.get('parameters', [])


class ApprovalService:
    """Service for handling approval operations"""

    def __init__(
        self,
        temporal_client: Optional[Client] = None,
        parameter_validator: Optional[ApprovalParameterValidator] = None
    ):
        self.temporal_client = temporal_client
        self.validator = parameter_validator or ApprovalParameterValidator()

    def _get_chain_logger(self, request) -> Optional[ChainLogger]:
        """Get or create chain logger from approval request's chain relationship."""
        if request.chain:
            return ChainLogger.create(
                chain_name=request.chain.name,
                version=request.chain.version,
                chain_id=request.chain.id,
            )
        return None

    async def get_approval_details(
        self,
        token: str
    ) -> Dict[str, Any]:
        """
        Get approval request details for viewing

        Args:
            token: Approval link token

        Returns:
            Dict with approval details

        Raises:
            ValueError: If token is invalid
        """
        with get_session() as session:
            # Validate token
            valid, error = validate_approval_link(session, token)
            if not valid:
                raise ValueError(error)

            # Get request
            request = get_approval_request_by_token(session, token)
            if not request:
                raise ValueError("Approval request not found")

            # Get artifact (via relationship)
            artifact = request.artifact

            return {
                "approval_request_id": request.id,
                "token": token,
                "status": request.status,
                "artifact": {
                    "id": artifact.id,
                    "filename": artifact.filename,
                    "file_type": artifact.file_type,
                    "view_url": request.artifact_view_url,
                    "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
                },
                "generation_info": {
                    "step_id": request.config_metadata.get('step_id'),
                    "workflow_name": request.config_metadata.get('workflow_name'),
                    "server": request.config_metadata.get('server'),
                    "parameters_used": request.config_metadata.get('parameters', {}),
                },
                "parameters_endpoint": f"/approval/{token}/parameters",
                "created_at": request.created_at.isoformat() if request.created_at else None,
                "expires_at": request.link_expires_at.isoformat() if request.link_expires_at else None,
            }

    async def get_editable_parameters(
        self,
        token: str
    ) -> Dict[str, Any]:
        """
        Get editable parameters from workflow registry

        Args:
            token: Approval link token

        Returns:
            Dict with parameter schema and current values

        Raises:
            ValueError: If token is invalid or workflow not found
        """
        with get_session() as session:
            # Validate token
            valid, error = validate_approval_link(session, token)
            if not valid:
                raise ValueError(error)

            # Get request
            request = get_approval_request_by_token(session, token)
            if not request:
                raise ValueError("Approval request not found")

            # Get workflow info from metadata
            workflow_name = request.config_metadata.get('workflow_name')
            server = request.config_metadata.get('server')
            current_parameters = request.config_metadata.get('parameters', {})

            # Get editable parameters from registry
            editable_params = self.validator.get_editable_parameters(workflow_name)
            if editable_params is None:
                raise ValueError(f"Workflow '{workflow_name}' not found in registry")

            # Build list of parameters with current values included
            parameters = []
            for param in editable_params:
                key = param['key']
                parameters.append({
                    "key": key,
                    "type": param.get('type', 'str'),
                    "category": param.get('category', 'other'),
                    "description": param.get('description', ''),
                    "default": param.get('default'),
                    "current_value": current_parameters.get(key, param.get('default')),
                })

            return {
                "workflow_name": workflow_name,
                "server": server,
                "parameters": parameters,
            }

    async def approve(
        self,
        token: str,
        decided_by: str
    ) -> Dict[str, Any]:
        """
        Approve an artifact

        Args:
            token: Approval link token
            decided_by: Identifier of approver

        Returns:
            Dict with approval result

        Raises:
            ValueError: If token is invalid
        """
        with get_session() as session:
            # Validate token
            valid, error = validate_approval_link(session, token)
            if not valid:
                raise ValueError(error)

            # Get request
            request = get_approval_request_by_token(session, token)
            if not request:
                raise ValueError("Approval request not found")

            # Get chain logger for gateway logging
            chain_logger = self._get_chain_logger(request)
            if chain_logger:
                chain_logger.gateway.info(f"Approval received for step {request.step_id} by {decided_by}")

            # Update DB
            updated_request = approve_approval_request(session, request.id, decided_by)

            # Send signal to Temporal workflow
            if self.temporal_client:
                await self._send_approval_signal(
                    updated_request.job_id,
                    updated_request.step_id,
                    decision="approved",
                    decided_by=decided_by,
                    parameters={},
                    comment=None,
                    chain_logger=chain_logger
                )
                if chain_logger:
                    chain_logger.gateway.info(f"Approval signal sent to workflow {updated_request.job_id}")
            else:
                if chain_logger:
                    chain_logger.gateway.warning("No Temporal client configured, signal not sent")

            return {
                "status": "approved",
                "approval_request_id": updated_request.id,
                "decided_by": decided_by,
                "workflow_signaled": self.temporal_client is not None,
            }

    async def reject(
        self,
        token: str,
        decided_by: str,
        parameters: Dict[str, Any],
        rejection_comment: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Reject an artifact with new parameters for regeneration

        Args:
            token: Approval link token
            decided_by: Identifier of who rejected
            parameters: New parameters for regeneration
            rejection_comment: Optional comment explaining rejection

        Returns:
            Dict with rejection result

        Raises:
            ValueError: If token is invalid or parameters are invalid
        """
        with get_session() as session:
            # Validate token
            valid, error = validate_approval_link(session, token)
            if not valid:
                raise ValueError(error)

            # Get request
            request = get_approval_request_by_token(session, token)
            if not request:
                raise ValueError("Approval request not found")

            # Get chain logger for gateway logging
            chain_logger = self._get_chain_logger(request)
            if chain_logger:
                chain_logger.gateway.info(f"Rejection received for step {request.step_id} by {decided_by}")
                if rejection_comment:
                    chain_logger.gateway.info(f"Rejection comment: {rejection_comment}")
                chain_logger.gateway.info(f"New parameters: {parameters}")

            # Get workflow name for validation
            workflow_name = request.config_metadata.get('workflow_name')

            # Validate parameters against registry
            params_valid, validation_errors = self.validator.validate_parameters(
                workflow_name,
                parameters
            )

            if not params_valid:
                if chain_logger:
                    chain_logger.gateway.error(f"Parameter validation failed: {validation_errors}")
                raise ValueError({
                    "error": "Invalid parameters provided",
                    "validation_errors": validation_errors,
                })

            # Update DB
            updated_request = reject_approval_request(session, request.id, decided_by)

            # Send signal to Temporal workflow
            if self.temporal_client:
                await self._send_approval_signal(
                    updated_request.job_id,
                    updated_request.step_id,
                    decision="rejected",
                    decided_by=decided_by,
                    parameters=parameters,
                    comment=rejection_comment,
                    chain_logger=chain_logger
                )
                if chain_logger:
                    chain_logger.gateway.info(f"Rejection signal sent to workflow {updated_request.job_id}, triggering regeneration")
            else:
                if chain_logger:
                    chain_logger.gateway.warning("No Temporal client configured, signal not sent")

            return {
                "status": "rejected",
                "approval_request_id": updated_request.id,
                "decided_by": decided_by,
                "regenerating_with_parameters": parameters,
                "workflow_signaled": self.temporal_client is not None,
            }

    async def _send_approval_signal(
        self,
        job_id: str,
        step_id: str,
        decision: str,
        decided_by: str,
        parameters: Dict[str, Any],
        comment: Optional[str],
        chain_logger: Optional[ChainLogger] = None
    ) -> None:
        """Send approval decision signal to Temporal workflow"""
        try:
            handle = self.temporal_client.get_workflow_handle(job_id)

            # Pack all data into a single dict
            signal_data = {
                "step_id": step_id,
                "decision": decision,
                "decided_by": decided_by,
                "parameters": parameters,
                "comment": comment
            }

            await handle.signal("approval_decision_signal", signal_data)

        except Exception as e:
            if chain_logger:
                chain_logger.gateway.error(f"Failed to send approval signal to job {job_id}: {e}")
            raise


# Global service singleton
_approval_service: Optional[ApprovalService] = None


def get_approval_service(
    temporal_client: Optional[Client] = None
) -> ApprovalService:
    """Get or create global approval service"""
    global _approval_service
    if _approval_service is None:
        _approval_service = ApprovalService(temporal_client=temporal_client)
    return _approval_service
