from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from crm_agent.constants import (
    BLOCKED_METHODS,
    MUTATING_METHODS,
    STANDARD_PROPERTY_ALLOWLIST,
    SUPPORTED_FIELD_TYPES,
    SUPPORTED_OBJECTS,
    SUPPORTED_PROPERTY_TYPES,
)
from crm_agent.io import slugify, stable_hash


class SourceRegistry(BaseModel):
    version: int = 1
    generated_from_plan_date: str
    sources: list[dict[str, Any]]
    principles: list[str] = Field(default_factory=list)


class PortalObjectCapabilities(BaseModel):
    object_type: str
    readable: bool = False
    writable: bool = False
    property_count: int = 0
    properties: dict[str, dict[str, Any]] = Field(default_factory=dict)
    pipelines: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class PortalCapabilities(BaseModel):
    generated_at: str
    api_version: str
    auth_mode: Literal["legacy_private_app"] = "legacy_private_app"
    account: dict[str, Any] = Field(default_factory=dict)
    rate_limits: dict[str, Any] = Field(default_factory=dict)
    supported_scope: Literal["crm_sales_core"] = "crm_sales_core"
    custom_objects_enabled: bool = False
    objects: dict[str, PortalObjectCapabilities]
    warnings: list[str] = Field(default_factory=list)

    def object_caps(self, object_type: str) -> PortalObjectCapabilities:
        return self.objects.get(
            object_type,
            PortalObjectCapabilities(object_type=object_type, errors=["Object not discovered"]),
        )


class BusinessContext(BaseModel):
    project_slug: str
    business_name: str
    industry: str | None = None
    sales_motion: str | None = None
    users: list[str] = Field(default_factory=list)
    sales_process_notes: str = ""
    data_requirements: list[dict[str, Any]] = Field(default_factory=list)
    reporting_goals: list[str] = Field(default_factory=list)
    source_documents: list[str] = Field(default_factory=list)
    raw_notes: str = ""
    out_of_scope: list[str] = Field(
        default_factory=lambda: [
            "workflows",
            "dashboards",
            "reports",
            "campaigns",
            "forms",
            "permissions",
            "custom_objects",
        ]
    )

    @field_validator("project_slug")
    @classmethod
    def normalize_project_slug(cls, value: str) -> str:
        return slugify(value)


class PropertySpec(BaseModel):
    object_type: Literal["companies", "contacts", "deals"]
    name: str
    label: str
    group_name: str
    type: str = "string"
    field_type: str = "text"
    description: str | None = None
    options: list[dict[str, Any]] = Field(default_factory=list)
    has_unique_value: bool = False
    allow_standard_property: bool = False

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return slugify(value)

    @field_validator("type")
    @classmethod
    def supported_type(cls, value: str) -> str:
        if value not in SUPPORTED_PROPERTY_TYPES:
            raise ValueError(f"Unsupported property type: {value}")
        return value

    @field_validator("field_type")
    @classmethod
    def supported_field_type(cls, value: str) -> str:
        if value not in SUPPORTED_FIELD_TYPES:
            raise ValueError(f"Unsupported fieldType: {value}")
        return value

    @model_validator(mode="after")
    def validate_property_shape(self) -> PropertySpec:
        if self.field_type in {"select", "radio", "checkbox"} and not self.options:
            raise ValueError(f"{self.name} needs options for fieldType {self.field_type}")
        if self.type != "enumeration" and self.options:
            raise ValueError(f"{self.name} cannot have options unless type is enumeration")
        return self

    def is_standard_property(self) -> bool:
        return self.name in STANDARD_PROPERTY_ALLOWLIST.get(self.object_type, set())

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "groupName": self.group_name,
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "fieldType": self.field_type,
            "hasUniqueValue": self.has_unique_value,
        }
        if self.description:
            payload["description"] = self.description
        if self.options:
            payload["options"] = self.options
        return payload


class PipelineStageSpec(BaseModel):
    label: str
    probability: str = "0.10"
    closed: bool = False
    display_order: int = 0

    @field_validator("probability")
    @classmethod
    def valid_probability(cls, value: str) -> str:
        numeric = float(value)
        if numeric < 0 or numeric > 1:
            raise ValueError("Stage probability must be between 0 and 1")
        return value

    def payload(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "displayOrder": self.display_order,
            "metadata": {
                "probability": self.probability,
                "isClosed": "true" if self.closed else "false",
            },
        }


class PipelineSpec(BaseModel):
    object_type: Literal["deals"] = "deals"
    label: str
    display_order: int = 0
    stages: list[PipelineStageSpec]

    @model_validator(mode="after")
    def validate_stage_labels(self) -> PipelineSpec:
        labels = [stage.label.lower().strip() for stage in self.stages]
        if len(labels) != len(set(labels)):
            raise ValueError("Pipeline stages must have unique labels")
        return self

    def payload(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "displayOrder": self.display_order,
            "stages": [stage.payload() for stage in self.stages],
        }


class CrmDesign(BaseModel):
    generated_at: str
    project_slug: str
    business_name: str
    scope: Literal["crm_sales_core"] = "crm_sales_core"
    properties: list[PropertySpec] = Field(default_factory=list)
    pipelines: list[PipelineSpec] = Field(default_factory=list)
    associations: list[dict[str, Any]] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @field_validator("project_slug")
    @classmethod
    def normalize_project_slug(cls, value: str) -> str:
        return slugify(value)


class ManifestOperation(BaseModel):
    id: str
    action: Literal[
        "ensure_property",
        "ensure_pipeline",
        "ensure_pipeline_stage",
        "ensure_association_label",
        "noop",
    ]
    object_type: str
    method: Literal["GET", "POST", "PATCH", "PUT", "DELETE"]
    endpoint: str
    payload: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    risk: Literal["low", "medium", "high"] = "low"
    rollback: str
    requires_approval: bool = True
    status: Literal["planned", "noop", "blocked", "applied", "failed"] = "planned"
    reason: str = ""

    @field_validator("object_type")
    @classmethod
    def supported_object(cls, value: str) -> str:
        if value not in SUPPORTED_OBJECTS:
            raise ValueError(f"Unsupported V1 object type: {value}")
        return value

    @field_validator("endpoint")
    @classmethod
    def relative_endpoint_only(cls, value: str) -> str:
        if value.startswith("http://") or value.startswith("https://"):
            raise ValueError("Endpoint must be a relative HubSpot API path")
        if not value.startswith("/"):
            raise ValueError("Endpoint must start with /")
        return value

    @model_validator(mode="after")
    def validate_write_contract(self) -> ManifestOperation:
        if self.method in BLOCKED_METHODS:
            raise ValueError("DELETE operations are blocked in V1")
        if self.action != "noop" and self.method not in MUTATING_METHODS:
            raise ValueError("Non-noop operations must use POST, PATCH, or PUT")
        return self


class HubSpotManifest(BaseModel):
    generated_at: str
    api_version: str
    project_slug: str
    design_hash: str
    capability_hash: str
    dry_run_required: bool = True
    operations: list[ManifestOperation]
    warnings: list[str] = Field(default_factory=list)

    @property
    def manifest_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json", exclude_none=True))

    @property
    def has_blockers(self) -> bool:
        return any(operation.status == "blocked" for operation in self.operations)

    @property
    def planned_operations(self) -> list[ManifestOperation]:
        return [
            operation
            for operation in self.operations
            if operation.status == "planned" and operation.action != "noop"
        ]


class ManifestApproval(BaseModel):
    manifest_hash: str
    approved_at: str
    approved_by: str = "local_user"
    note: str = "Validated manifest approved for supervised apply."


class ValidationReport(BaseModel):
    generated_at: str
    manifest_hash: str
    passed: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    approval: ManifestApproval | None = None
