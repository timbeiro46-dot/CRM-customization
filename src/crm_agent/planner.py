from __future__ import annotations

from crm_agent.io import stable_hash, utc_now_iso
from crm_agent.models import (
    CrmDesign,
    CrmReconciliation,
    HubSpotManifest,
    ManifestOperation,
    PipelineSpec,
    PortalCapabilities,
    PropertySpec,
    ReconciliationDecision,
)


def build_manifest(
    design: CrmDesign,
    capabilities: PortalCapabilities,
    reconciliation: CrmReconciliation | None = None,
) -> HubSpotManifest:
    if reconciliation:
        _validate_reconciliation_current(design, capabilities, reconciliation)

    operations: list[ManifestOperation] = []
    warnings: list[str] = list(reconciliation.warnings) if reconciliation else []

    for prop in design.properties:
        decision = (
            reconciliation.decision_for(
                kind="property",
                object_type=prop.object_type,
                desired_name=prop.name,
                desired_label=prop.label,
            )
            if reconciliation
            else None
        )
        if decision and decision.decision != "create_new":
            operations.extend(_property_operations_from_decision(prop, capabilities, decision))
            continue

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
        decision = (
            reconciliation.decision_for(
                kind="pipeline",
                object_type=pipeline.object_type,
                desired_name=None,
                desired_label=pipeline.label,
            )
            if reconciliation
            else None
        )
        if decision and decision.decision != "create_new":
            operations.extend(_pipeline_operations_from_decision(pipeline, capabilities, decision))
            continue

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
        reconciliation_hash=stable_hash(reconciliation) if reconciliation else None,
        operations=operations,
        warnings=warnings,
    )


def _property_operations_from_decision(
    prop: PropertySpec,
    capabilities: PortalCapabilities,
    decision: ReconciliationDecision,
) -> list[ManifestOperation]:
    operation_id = f"property:{prop.object_type}:{prop.name}"
    endpoint = f"/crm/properties/{capabilities.api_version}/{prop.object_type}"
    existing_name = decision.existing_name or prop.name
    if decision.decision == "reuse_existing":
        return [
            ManifestOperation(
                id=operation_id,
                action="noop",
                object_type=prop.object_type,
                method="POST",
                endpoint=endpoint,
                payload=prop.payload(),
                expected={
                    "name": existing_name,
                    "label": decision.existing_label or prop.label,
                    "mapped_from": prop.name,
                },
                rollback="No change planned.",
                requires_approval=False,
                status="noop",
                reason=(
                    "Reconciliation maps this design property to an existing HubSpot property: "
                    f"{existing_name}."
                ),
            )
        ]
    if decision.decision == "extend_existing":
        option_changes = [
            change
            for change in decision.additive_changes
            if change.get("type") == "add_enum_options" and change.get("options")
        ]
        if option_changes:
            return [
                ManifestOperation(
                    id=f"property_options:{prop.object_type}:{existing_name}",
                    action="extend_property_options",
                    object_type=prop.object_type,
                    method="PATCH",
                    endpoint=(
                        f"/crm/properties/{capabilities.api_version}/"
                        f"{prop.object_type}/{existing_name}"
                    ),
                    payload={
                        "name": existing_name,
                        "options_to_add": option_changes[0]["options"],
                    },
                    expected={"name": existing_name, "mapped_from": prop.name},
                    risk="medium",
                    rollback=(
                        "Manual review is required to hide or remove enum options. "
                        "V1 does not perform destructive option cleanup."
                    ),
                    reason=decision.reason,
                )
            ]
    return [
        ManifestOperation(
            id=operation_id,
            action="noop",
            object_type=prop.object_type,
            method="POST",
            endpoint=endpoint,
            payload=prop.payload(),
            expected={"name": prop.name},
            risk="high",
            rollback="Manual reconciliation required before planning writes.",
            status="blocked",
            reason=f"Reconciliation decision {decision.decision}: {decision.reason}",
        )
    ]


def _pipeline_operations_from_decision(
    pipeline: PipelineSpec,
    capabilities: PortalCapabilities,
    decision: ReconciliationDecision,
) -> list[ManifestOperation]:
    operation_id = f"pipeline:{pipeline.object_type}:{pipeline.label}"
    endpoint = f"/crm/pipelines/{capabilities.api_version}/{pipeline.object_type}"
    if decision.decision in {"blocked_conflict", "needs_review", "out_of_scope"}:
        return [
            ManifestOperation(
                id=operation_id,
                action="noop",
                object_type=pipeline.object_type,
                method="POST",
                endpoint=endpoint,
                payload=pipeline.payload(),
                expected={"label": pipeline.label},
                risk="high",
                rollback="Manual reconciliation required before planning writes.",
                status="blocked",
                reason=f"Reconciliation decision {decision.decision}: {decision.reason}",
            )
        ]

    target_label = decision.existing_label or pipeline.label
    caps = capabilities.object_caps(pipeline.object_type)
    existing = _find_pipeline(caps.pipelines, target_label)
    if not existing:
        return [
            ManifestOperation(
                id=operation_id,
                action="noop",
                object_type=pipeline.object_type,
                method="POST",
                endpoint=endpoint,
                payload=pipeline.payload(),
                expected={"label": target_label},
                risk="high",
                rollback="Re-run audit/preflight before planning pipeline writes.",
                status="blocked",
                reason=(
                    "Reconciliation references an existing pipeline that is absent from the "
                    "current capabilities file."
                ),
            )
        ]

    operations = [
        ManifestOperation(
            id=operation_id,
            action="noop",
            object_type=pipeline.object_type,
            method="POST",
            endpoint=endpoint,
            payload=pipeline.payload(),
            expected={"label": target_label, "mapped_from": pipeline.label},
            rollback="No change planned.",
            requires_approval=False,
            status="noop",
            reason=f"Reconciliation maps this design pipeline to `{target_label}`.",
        )
    ]
    existing_stage_labels = {
        stage.get("label", "").lower().strip() for stage in existing.get("stages", [])
    }
    for stage in pipeline.stages:
        if stage.label.lower().strip() in existing_stage_labels:
            continue
        operations.append(
            ManifestOperation(
                id=f"stage:{pipeline.object_type}:{target_label}:{stage.label}",
                action="ensure_pipeline_stage",
                object_type=pipeline.object_type,
                method="POST",
                endpoint=(
                    f"/crm/pipelines/{capabilities.api_version}/"
                    f"{pipeline.object_type}/{existing['id']}/stages"
                ),
                payload=stage.payload(),
                expected={"pipeline_label": target_label, "label": stage.label},
                risk="medium",
                rollback="Manually archive the stage if it is unused. V1 does not delete stages.",
                reason=decision.reason,
            )
        )
    return operations


def _validate_reconciliation_current(
    design: CrmDesign,
    capabilities: PortalCapabilities,
    reconciliation: CrmReconciliation,
) -> None:
    if reconciliation.design_hash != stable_hash(design):
        raise ValueError(
            "Reconciliation design hash does not match the current design. Re-run reconcile."
        )
    if reconciliation.capability_hash != stable_hash(capabilities):
        raise ValueError(
            "Reconciliation capability hash does not match the current capabilities. "
            "Re-run audit and reconcile."
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
