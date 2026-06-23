from __future__ import annotations

from crm_agent.io import stable_hash, utc_now_iso
from crm_agent.models import CrmDesign, HubSpotManifest, ManifestOperation, PortalCapabilities


def build_manifest(design: CrmDesign, capabilities: PortalCapabilities) -> HubSpotManifest:
    operations: list[ManifestOperation] = []
    warnings: list[str] = []

    for prop in design.properties:
        caps = capabilities.object_caps(prop.object_type)
        existing = caps.properties.get(prop.name)
        operation_id = f"property:{prop.object_type}:{prop.name}"
        if not caps.writable:
            operations.append(
                ManifestOperation(
                    id=operation_id,
                    action="noop",
                    object_type=prop.object_type,
                    method="POST",
                    endpoint=f"/crm/properties/{capabilities.api_version}/{prop.object_type}",
                    payload=prop.payload(),
                    expected={"name": prop.name},
                    risk="medium",
                    rollback="Manual archive is required; V1 does not delete properties.",
                    status="blocked",
                    reason=f"{prop.object_type} was not discovered as writable.",
                )
            )
            continue
        if existing:
            if _property_matches(prop.payload(), existing):
                operations.append(
                    ManifestOperation(
                        id=operation_id,
                        action="noop",
                        object_type=prop.object_type,
                        method="POST",
                        endpoint=f"/crm/properties/{capabilities.api_version}/{prop.object_type}",
                        payload=prop.payload(),
                        expected={"name": prop.name},
                        risk="low",
                        rollback="No change planned.",
                        requires_approval=False,
                        status="noop",
                        reason="Property already exists with compatible shape.",
                    )
                )
            else:
                operations.append(
                    ManifestOperation(
                        id=operation_id,
                        action="noop",
                        object_type=prop.object_type,
                        method="POST",
                        endpoint=f"/crm/properties/{capabilities.api_version}/{prop.object_type}",
                        payload=prop.payload(),
                        expected={"name": prop.name},
                        risk="high",
                        rollback="Manual review required before changing an existing property.",
                        status="blocked",
                        reason=(
                            "Existing property has a conflicting type, fieldType, or option set."
                        ),
                    )
                )
            continue
        operations.append(
            ManifestOperation(
                id=operation_id,
                action="ensure_property",
                object_type=prop.object_type,
                method="POST",
                endpoint=f"/crm/properties/{capabilities.api_version}/{prop.object_type}",
                payload=prop.payload(),
                expected={"name": prop.name, "label": prop.label},
                risk="low",
                rollback="Archive the created property manually if the design is abandoned.",
            )
        )

    for pipeline in design.pipelines:
        caps = capabilities.object_caps(pipeline.object_type)
        existing = _find_pipeline(caps.pipelines, pipeline.label)
        operation_id = f"pipeline:{pipeline.object_type}:{pipeline.label}"
        if existing:
            operations.append(
                ManifestOperation(
                    id=operation_id,
                    action="noop",
                    object_type=pipeline.object_type,
                    method="POST",
                    endpoint=f"/crm/pipelines/{capabilities.api_version}/{pipeline.object_type}",
                    payload=pipeline.payload(),
                    expected={"label": pipeline.label},
                    rollback="No change planned.",
                    requires_approval=False,
                    status="noop",
                    reason="Pipeline already exists.",
                )
            )
            existing_stage_labels = {
                stage.get("label", "").lower().strip() for stage in existing.get("stages", [])
            }
            for stage in pipeline.stages:
                if stage.label.lower().strip() in existing_stage_labels:
                    continue
                operations.append(
                    ManifestOperation(
                        id=f"stage:{pipeline.object_type}:{pipeline.label}:{stage.label}",
                        action="ensure_pipeline_stage",
                        object_type=pipeline.object_type,
                        method="POST",
                        endpoint=(
                            f"/crm/pipelines/{capabilities.api_version}/"
                            f"{pipeline.object_type}/{existing['id']}/stages"
                        ),
                        payload=stage.payload(),
                        expected={"pipeline_label": pipeline.label, "label": stage.label},
                        risk="medium",
                        rollback=(
                            "Manually archive the stage if it is unused. V1 does not delete stages."
                        ),
                    )
                )
        else:
            operations.append(
                ManifestOperation(
                    id=operation_id,
                    action="ensure_pipeline",
                    object_type=pipeline.object_type,
                    method="POST",
                    endpoint=f"/crm/pipelines/{capabilities.api_version}/{pipeline.object_type}",
                    payload=pipeline.payload(),
                    expected={"label": pipeline.label},
                    risk="medium",
                    rollback=(
                        "Manually archive the created pipeline after moving records. "
                        "V1 does not delete pipelines."
                    ),
                )
            )

    if not operations:
        warnings.append("No operations were generated.")

    return HubSpotManifest(
        generated_at=utc_now_iso(),
        api_version=capabilities.api_version,
        project_slug=design.project_slug,
        design_hash=stable_hash(design),
        capability_hash=stable_hash(capabilities),
        operations=operations,
        warnings=warnings,
    )


def _find_pipeline(pipelines: list[dict], label: str) -> dict | None:
    for pipeline in pipelines:
        if pipeline.get("label", "").lower().strip() == label.lower().strip():
            return pipeline
    return None


def _property_matches(planned: dict, existing: dict) -> bool:
    if planned.get("type") != existing.get("type"):
        return False
    if planned.get("fieldType") != existing.get("fieldType"):
        return False
    planned_options = {
        str(item.get("value"))
        for item in planned.get("options", [])
        if item.get("value") is not None
    }
    if planned_options:
        existing_options = {
            str(item.get("value"))
            for item in existing.get("options", [])
            if item.get("value") is not None and not item.get("hidden")
        }
        return planned_options.issubset(existing_options)
    return True
