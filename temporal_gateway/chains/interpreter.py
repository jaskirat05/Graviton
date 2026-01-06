"""
Chain Interpreter

Parses chain definitions (YAML), validates them, builds DAG, and creates execution plans.
"""

import yaml
from graphlib import TopologicalSorter
from typing import Dict, Any, List, Set, Optional
from pathlib import Path
import re
from jinja2 import Environment, Template, TemplateSyntaxError, UndefinedError
from simpleeval import simple_eval, NameNotDefined

from .models import (
    ChainDefinition,
    ChainStepDefinition,
    StepResult
)


class ChainValidationError(Exception):
    """Raised when chain definition is invalid"""
    pass


class TemplateResolutionError(Exception):
    """Raised when template resolution fails"""
    pass


class ChainInterpreter:
    """
    Interprets chain definitions and provides validation/template utilities

    Responsibilities:
    1. Parse YAML chain definitions
    2. Validate chain structure and dependencies
    3. Build dependency DAG using graphlib
    4. Resolve Jinja2 templates in parameters
    5. Evaluate conditions
    """

    def __init__(self):
        self.jinja_env = Environment(
            variable_start_string='{{',
            variable_end_string='}}',
            autoescape=False
        )

    def load_from_yaml(self, yaml_path: Path) -> ChainDefinition:
        """
        Load and parse chain definition from YAML file

        Args:
            yaml_path: Path to YAML file

        Returns:
            ChainDefinition object

        Raises:
            ChainValidationError: If YAML is invalid or chain structure is wrong
        """
        try:
            with open(yaml_path, 'r') as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ChainValidationError(f"Invalid YAML: {e}")
        except FileNotFoundError:
            raise ChainValidationError(f"Chain file not found: {yaml_path}")

        return self.load_from_dict(data)

    def load_from_dict(self, data: Dict[str, Any]) -> ChainDefinition:
        """
        Load chain definition from dictionary

        Args:
            data: Chain definition as dict

        Returns:
            ChainDefinition object

        Raises:
            ChainValidationError: If chain structure is invalid
        """
        try:
            return ChainDefinition(**data)
        except Exception as e:
            raise ChainValidationError(f"Invalid chain definition: {e}")

    def validate_dependencies(self, chain: ChainDefinition) -> None:
        """
        Validate that all dependencies reference existing steps

        Args:
            chain: Chain definition to validate

        Raises:
            ChainValidationError: If dependencies are invalid
        """
        step_ids = {step.id for step in chain.steps}

        for step in chain.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    raise ChainValidationError(
                        f"Step '{step.id}' depends on unknown step '{dep}'"
                    )

    def build_dag(self, chain: ChainDefinition) -> TopologicalSorter:
        """
        Build dependency DAG from chain definition

        Args:
            chain: Chain definition

        Returns:
            TopologicalSorter with dependency graph

        Raises:
            ChainValidationError: If chain contains cycles
        """
        ts = TopologicalSorter()

        # Add all steps with their dependencies
        for step in chain.steps:
            if step.depends_on:
                ts.add(step.id, *step.depends_on)
            else:
                ts.add(step.id)

        # Validate no cycles
        try:
            # Prepare will raise CycleError if there's a cycle
            ts.prepare()
        except Exception as e:
            raise ChainValidationError(f"Chain contains circular dependencies: {e}")

        return ts

    def resolve_templates(
        self,
        parameters: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Resolve Jinja2 templates in parameters using context

        Args:
            parameters: Parameters that may contain templates like {{ step1.output.video }}
            context: Context data (previous step results) for template resolution

        Returns:
            Parameters with templates resolved

        Raises:
            TemplateResolutionError: If template resolution fails

        Example:
            >>> parameters = {"input": "{{ step1.output.video }}", "width": "{{ step1.width * 2 }}"}
            >>> context = {"step1": {"output": {"video": "out.mp4"}, "width": 512}}
            >>> resolve_templates(parameters, context)
            {"input": "out.mp4", "width": 1024}
        """
        resolved = {}

        for key, value in parameters.items():
            try:
                resolved[key] = self._resolve_value(value, context)
            except (TemplateSyntaxError, UndefinedError) as e:
                raise TemplateResolutionError(
                    f"Failed to resolve template in parameter '{key}': {e}"
                )

        return resolved

    def _resolve_value(self, value: Any, context: Dict[str, Any]) -> Any:
        """
        Recursively resolve a value that may contain templates

        Args:
            value: Value to resolve (can be str, dict, list, or primitive)
            context: Template context

        Returns:
            Resolved value
        """
        if isinstance(value, str):
            # Check if it contains Jinja2 template markers
            if '{{' in value and '}}' in value:
                template = self.jinja_env.from_string(value)
                result = template.render(**context)

                # Try to convert to appropriate type
                # If template result is a pure number string, convert it
                if result.isdigit():
                    return int(result)
                try:
                    return float(result)
                except ValueError:
                    return result

            return value

        elif isinstance(value, dict):
            return {k: self._resolve_value(v, context) for k, v in value.items()}

        elif isinstance(value, list):
            return [self._resolve_value(item, context) for item in value]

        else:
            # Return primitives as-is
            return value

    def evaluate_condition(
        self,
        condition: str,
        context: Dict[str, Any]
    ) -> bool:
        """
        Evaluate a condition expression

        Args:
            condition: Jinja2 condition expression (e.g., "{{ step1.score > 0.8 }}")
            context: Context data for evaluation

        Returns:
            True if condition passes, False otherwise

        Raises:
            TemplateResolutionError: If condition evaluation fails

        Example:
            >>> evaluate_condition("{{ step1.score > 0.8 }}", {"step1": {"score": 0.9}})
            True
        """
        try:
            # First resolve the template to get the expression
            template = self.jinja_env.from_string(condition)
            expression = template.render(**context)

            # Then evaluate the expression safely
            result = simple_eval(expression, names=context)

            if not isinstance(result, bool):
                raise TemplateResolutionError(
                    f"Condition must evaluate to boolean, got {type(result)}: {result}"
                )

            return result

        except (TemplateSyntaxError, UndefinedError, NameNotDefined) as e:
            raise TemplateResolutionError(f"Failed to evaluate condition '{condition}': {e}")
        except Exception as e:
            raise TemplateResolutionError(f"Condition evaluation error: {e}")

    def build_execution_context(
        self,
        step_results: Dict[str, StepResult]
    ) -> Dict[str, Any]:
        """
        Build context for template resolution from step results

        Args:
            step_results: Results from previous steps

        Returns:
            Context dict mapping step_id to result data

        Example:
            >>> results = {"step1": StepResult(step_id="step1", output={"video": "out.mp4"})}
            >>> build_execution_context(results)
            {"step1": {"output": {"video": "out.mp4"}, "parameters": {...}}}
        """
        context = {}

        for step_id, result in step_results.items():
            # Handle both StepResult objects and dicts (Temporal serializes to dicts)
            if isinstance(result, dict):
                context[step_id] = {
                    "output": result.get("output") or {},
                    "parameters": result.get("parameters") or {},
                    "status": result.get("status"),
                }
            else:
                context[step_id] = {
                    "output": result.output or {},
                    "parameters": result.parameters or {},
                    "status": result.status,
                }

        return context

