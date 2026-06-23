from __future__ import annotations

from crm_agent.constants import DEFAULT_DEAL_STAGES
from crm_agent.io import slugify, utc_now_iso
from crm_agent.models import (
    BusinessContext,
    CrmDesign,
    PipelineSpec,
    PipelineStageSpec,
    PortalCapabilities,
    PropertySpec,
)


def build_design(context: BusinessContext, capabilities: PortalCapabilities) -> CrmDesign:
    properties = _build_property_specs(context)
    stages = [
        PipelineStageSpec(
            label=item["label"],
            probability=item["probability"],
            closed=item["closed"],
            display_order=index,
        )
        for index, item in enumerate(DEFAULT_DEAL_STAGES)
    ]
    pipelines = [
        PipelineSpec(
            object_type="deals",
            label=f"{context.business_name} Sales Pipeline",
            display_order=0,
            stages=stages,
        )
    ]

    assumptions = [
        "V1 uses standard CRM/Sales objects only.",
        "Custom properties use the project slug as an internal-name namespace.",
        "Workflow, report, dashboard, form, campaign, and permission changes are out of scope.",
    ]
    if not capabilities.custom_objects_enabled:
        assumptions.append("Custom objects are disabled or intentionally gated for V1.")

    return CrmDesign(
        generated_at=utc_now_iso(),
        project_slug=context.project_slug,
        business_name=context.business_name,
        properties=properties,
        pipelines=pipelines,
        exclusions=context.out_of_scope,
        assumptions=assumptions,
    )


def _build_property_specs(context: BusinessContext) -> list[PropertySpec]:
    specs: list[PropertySpec] = []
    for requirement in context.data_requirements:
        object_type = requirement.get("object_type", "companies")
        raw_name = requirement.get("field_name") or requirement.get("name")
        if not raw_name:
            continue
        label = requirement.get("label") or raw_name.replace("_", " ").title()
        internal_name = (
            requirement.get("hubspot_property") or f"{context.project_slug}_{slugify(raw_name)}"
        )
        options = [
            {"label": str(option), "value": slugify(str(option))}
            for option in requirement.get("options", [])
        ]
        group_name = requirement.get("group_name") or _default_group_name(object_type)
        specs.append(
            PropertySpec(
                object_type=object_type,
                name=internal_name,
                label=label,
                group_name=group_name,
                type=requirement.get("type", "string"),
                field_type=requirement.get("field_type", requirement.get("fieldType", "text")),
                description=requirement.get("reason"),
                options=options,
                has_unique_value=bool(requirement.get("has_unique_value", False)),
                allow_standard_property=bool(requirement.get("allow_standard_property", False)),
            )
        )
    return specs


def _default_group_name(object_type: str) -> str:
    return {
        "companies": "companyinformation",
        "contacts": "contactinformation",
        "deals": "dealinformation",
    }[object_type]
