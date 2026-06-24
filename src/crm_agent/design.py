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
    stages = _build_pipeline_stages(context)
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


def _build_pipeline_stages(context: BusinessContext) -> list[PipelineStageSpec]:
    if not context.pipeline_stages:
        return [
            PipelineStageSpec(
                label=item["label"],
                probability=item["probability"],
                closed=item["closed"],
                display_order=index,
            )
            for index, item in enumerate(DEFAULT_DEAL_STAGES)
        ]

    labels = _ensure_closed_stages(context.pipeline_stages)
    non_closed_count = sum(1 for label in labels if not _closed_kind(label))
    open_index = 0
    stages: list[PipelineStageSpec] = []
    for index, label in enumerate(labels):
        closed_kind = _closed_kind(label)
        if closed_kind == "won":
            probability = "1.0"
            closed = True
        elif closed_kind == "lost":
            probability = "0.0"
            closed = True
        else:
            open_index += 1
            probability = _open_probability(open_index, non_closed_count)
            closed = False
        stages.append(
            PipelineStageSpec(
                label=label,
                probability=probability,
                closed=closed,
                display_order=index,
            )
        )
    return stages


def _ensure_closed_stages(labels: list[str]) -> list[str]:
    unique = []
    seen: set[str] = set()
    for label in labels:
        normalized = label.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(label.strip())
    if not any(_closed_kind(label) == "won" for label in unique):
        unique.append("Closed Won")
    if not any(_closed_kind(label) == "lost" for label in unique):
        unique.append("Closed Lost")
    return unique


def _closed_kind(label: str) -> str | None:
    normalized = slugify(label)
    if normalized in {"closed_won", "ganado", "cerrado_ganado"}:
        return "won"
    if normalized in {"closed_lost", "perdido", "cerrado_perdido"}:
        return "lost"
    return None


def _open_probability(position: int, total: int) -> str:
    if total <= 1:
        return "0.10"
    ratio = position / total
    value = min(0.85, max(0.10, ratio * 0.80))
    return f"{value:.2f}"


def _default_group_name(object_type: str) -> str:
    return {
        "companies": "companyinformation",
        "contacts": "contactinformation",
        "deals": "dealinformation",
    }[object_type]
