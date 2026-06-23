from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from crm_agent.io import stable_hash, utc_now_iso
from crm_agent.models import (
    AuditObjectMetadata,
    AuditPipelineMetric,
    AuditPropertyMetric,
    CrmAudit,
    CrmDesign,
    CrmReconciliation,
    PipelineSpec,
    PropertySpec,
    ReconciliationDecision,
)


def reconcile_design_with_audit(design: CrmDesign, audit: CrmAudit) -> CrmReconciliation:
    decisions: list[ReconciliationDecision] = []
    findings: list[dict[str, Any]] = list(audit.findings)
    warnings: list[str] = []

    for prop in design.properties:
        metadata = audit.objects.get(prop.object_type)
        decisions.append(_property_decision(prop, metadata))

    for pipeline in design.pipelines:
        metadata = audit.objects.get(pipeline.object_type)
        decisions.append(_pipeline_decision(pipeline, metadata))

    blockers = [item for item in decisions if item.decision in {"blocked_conflict", "needs_review"}]
    if blockers:
        warnings.append(
            f"{len(blockers)} reconciliation decision(s) require manual review before planning."
        )

    return CrmReconciliation(
        generated_at=utc_now_iso(),
        design_hash=stable_hash(design),
        audit_hash=audit.audit_hash,
        capability_hash=audit.capability_hash,
        decisions=decisions,
        findings=findings,
        warnings=warnings,
    )


def _property_decision(
    desired: PropertySpec, metadata: AuditObjectMetadata | None
) -> ReconciliationDecision:
    decision_id = f"property:{desired.object_type}:{desired.name}"
    if metadata is None or metadata.availability.status == "not_available":
        return ReconciliationDecision(
            id=decision_id,
            kind="property",
            object_type=desired.object_type,
            desired_name=desired.name,
            desired_label=desired.label,
            decision="out_of_scope",
            confidence=0,
            reason="Object was not available in the audit; no existing-asset reuse can be proven.",
        )

    by_name = {prop.name: prop for prop in metadata.properties}
    if existing := by_name.get(desired.name):
        compatible, compatibility = _property_compatibility(desired, existing)
        return ReconciliationDecision(
            id=decision_id,
            kind="property",
            object_type=desired.object_type,
            desired_name=desired.name,
            desired_label=desired.label,
            decision="reuse_existing" if compatible else "blocked_conflict",
            confidence=1.0,
            existing_name=existing.name,
            existing_label=existing.label,
            compatibility=compatibility,
            reason=(
                "Exact internal-name match is compatible."
                if compatible
                else "Exact internal-name match has incompatible shape."
            ),
        )

    label_matches = [
        prop
        for prop in metadata.properties
        if _normalize(prop.label or prop.name) == _normalize(desired.label)
    ]
    for existing in label_matches:
        compatible, compatibility = _property_compatibility(desired, existing)
        if not compatible:
            return ReconciliationDecision(
                id=decision_id,
                kind="property",
                object_type=desired.object_type,
                desired_name=desired.name,
                desired_label=desired.label,
                decision="blocked_conflict",
                confidence=0.9,
                existing_name=existing.name,
                existing_label=existing.label,
                compatibility=compatibility,
                reason="Existing property has the same normalized label but incompatible shape.",
            )
        missing_options = _missing_options(desired, existing)
        if missing_options:
            return ReconciliationDecision(
                id=decision_id,
                kind="property",
                object_type=desired.object_type,
                desired_name=desired.name,
                desired_label=desired.label,
                decision="extend_existing",
                confidence=0.9,
                existing_name=existing.name,
                existing_label=existing.label,
                compatibility=compatibility,
                additive_changes=[{"type": "add_enum_options", "options": missing_options}],
                reason="Existing property has the same label and compatible enum shape.",
            )
        return ReconciliationDecision(
            id=decision_id,
            kind="property",
            object_type=desired.object_type,
            desired_name=desired.name,
            desired_label=desired.label,
            decision="reuse_existing",
            confidence=0.93,
            existing_name=existing.name,
            existing_label=existing.label,
            compatibility=compatibility,
            reason="Existing property has the same normalized label and compatible shape.",
        )

    similar = _best_label_match(desired.label, metadata.properties)
    if similar and similar[1] >= 0.82:
        existing, confidence = similar
        compatible, compatibility = _property_compatibility(desired, existing)
        return ReconciliationDecision(
            id=decision_id,
            kind="property",
            object_type=desired.object_type,
            desired_name=desired.name,
            desired_label=desired.label,
            decision="needs_review" if compatible else "blocked_conflict",
            confidence=round(confidence, 4),
            existing_name=existing.name,
            existing_label=existing.label,
            compatibility=compatibility,
            reason="Similar property label found; manual confirmation is required.",
        )

    return ReconciliationDecision(
        id=decision_id,
        kind="property",
        object_type=desired.object_type,
        desired_name=desired.name,
        desired_label=desired.label,
        decision="create_new",
        confidence=1.0,
        reason="No compatible existing property was found.",
    )


def _pipeline_decision(
    desired: PipelineSpec, metadata: AuditObjectMetadata | None
) -> ReconciliationDecision:
    decision_id = f"pipeline:{desired.object_type}:{desired.label}"
    if metadata is None or metadata.availability.status == "not_available":
        return ReconciliationDecision(
            id=decision_id,
            kind="pipeline",
            object_type=desired.object_type,
            desired_label=desired.label,
            decision="out_of_scope",
            confidence=0,
            reason="Pipeline object was not available in the audit.",
        )

    for existing in metadata.pipelines:
        if _normalize(existing.label) != _normalize(desired.label):
            continue
        missing_stages = _missing_stages(desired, existing)
        return ReconciliationDecision(
            id=decision_id,
            kind="pipeline",
            object_type=desired.object_type,
            desired_label=desired.label,
            decision="extend_existing" if missing_stages else "reuse_existing",
            confidence=0.95,
            existing_id=existing.id,
            existing_label=existing.label,
            compatibility={
                "label_match": "normalized_exact",
                "missing_stage_labels": missing_stages,
            },
            additive_changes=[{"type": "add_pipeline_stages", "stage_labels": missing_stages}]
            if missing_stages
            else [],
            reason=(
                "Existing pipeline has missing desired stages."
                if missing_stages
                else "Existing pipeline label matches desired design."
            ),
        )

    similar = _best_pipeline_label_match(desired.label, metadata.pipelines)
    if similar and similar[1] >= 0.82:
        existing, confidence = similar
        return ReconciliationDecision(
            id=decision_id,
            kind="pipeline",
            object_type=desired.object_type,
            desired_label=desired.label,
            decision="needs_review",
            confidence=round(confidence, 4),
            existing_id=existing.id,
            existing_label=existing.label,
            compatibility={"label_similarity": round(confidence, 4)},
            reason="Similar pipeline label found; manual confirmation is required.",
        )

    return ReconciliationDecision(
        id=decision_id,
        kind="pipeline",
        object_type=desired.object_type,
        desired_label=desired.label,
        decision="create_new",
        confidence=1.0,
        reason="No compatible existing pipeline was found.",
    )


def _property_compatibility(
    desired: PropertySpec, existing: AuditPropertyMetric
) -> tuple[bool, dict[str, Any]]:
    type_matches = desired.type == existing.type
    field_type_matches = desired.field_type == existing.field_type
    desired_options = _option_values(desired.options)
    existing_options = _option_values(existing.options)
    option_overlap = _overlap_ratio(desired_options, existing_options)
    options_compatible = True
    if desired_options:
        options_compatible = bool(existing_options) and (
            desired_options.issubset(existing_options) or option_overlap >= 0.6
        )
    compatibility = {
        "type_matches": type_matches,
        "field_type_matches": field_type_matches,
        "desired_options": sorted(desired_options),
        "existing_options": sorted(existing_options),
        "option_overlap": round(option_overlap, 4),
    }
    return type_matches and field_type_matches and options_compatible, compatibility


def _missing_options(desired: PropertySpec, existing: AuditPropertyMetric) -> list[dict[str, Any]]:
    existing_values = _option_values(existing.options)
    return [
        {"label": item.get("label"), "value": item.get("value")}
        for item in desired.options
        if item.get("value") not in existing_values
    ]


def _missing_stages(desired: PipelineSpec, existing: AuditPipelineMetric) -> list[str]:
    existing_labels = {_normalize(stage.label) for stage in existing.stages}
    return [
        stage.label for stage in desired.stages if _normalize(stage.label) not in existing_labels
    ]


def _best_label_match(
    label: str, properties: list[AuditPropertyMetric]
) -> tuple[AuditPropertyMetric, float] | None:
    scored = [
        (
            prop,
            SequenceMatcher(None, _normalize(label), _normalize(prop.label or prop.name)).ratio(),
        )
        for prop in properties
    ]
    return max(scored, key=lambda item: item[1], default=None)


def _best_pipeline_label_match(
    label: str, pipelines: list[AuditPipelineMetric]
) -> tuple[AuditPipelineMetric, float] | None:
    scored = [
        (pipeline, SequenceMatcher(None, _normalize(label), _normalize(pipeline.label)).ratio())
        for pipeline in pipelines
    ]
    return max(scored, key=lambda item: item[1], default=None)


def _option_values(options: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("value"))
        for item in options
        if item.get("value") is not None and not item.get("hidden")
    }


def _overlap_ratio(desired: set[str], existing: set[str]) -> float:
    if not desired:
        return 1.0
    return len(desired.intersection(existing)) / len(desired)


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
