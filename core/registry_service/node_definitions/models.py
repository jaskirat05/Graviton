"""Pydantic models for node-definition CRUD endpoints."""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class NodeDefinitionParametersReplaceRequest(BaseModel):
    parameters: List[Dict[str, Any]] = Field(default_factory=list)


class NodeDefinitionParameterPatchRequest(BaseModel):
    upserts: List[Dict[str, Any]] = Field(default_factory=list)
    remove_keys: List[str] = Field(default_factory=list)

