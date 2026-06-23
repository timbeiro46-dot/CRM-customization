from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from crm_agent.audit_registry import AuditModule, select_audit_modules
from crm_agent.errors import HubSpotApiError
from crm_agent.hubspot import HubSpotConnector
from crm_agent.io import stable_hash, utc_now_iso
from crm_agent.models import (
    AuditAvailability,
    AuditHubResult,
    AuditObjectMetadata,
    AuditPipelineMetric,
    AuditPipelineStage,
    AuditPropertyMetric,
    CrmAudit,
    PortalCapabilities,
)

COMMON_ASSOCIATION_PAIRS = (
    ("companies", "contacts"),
    ("companies", "deals"),
    ("contacts", "deals"),
    ("deals", "line_items"),
    ("deals", "tickets"),
)


def build_audit(
    capabilities: PortalCapabilities,
    *,
    connector: HubSpotConnector | None = None,
    hubs: str = "auto",
    depth: str = "metadata-quality",
    sample_limit: int = 25,
) -> CrmAudit:
    modules = select_audit_modules(hubs)
    objects: dict[str, AuditObjectMetadata] = {}
    hub_results: dict[str, AuditHubResult] = {}
    warnings: list[str] = []
    findings: list[dict[str, Any]] = []
    custom_object_schemas: list[dict[str, Any]] = []

    for module in modules:
        if module.hub == "unknown":
            hub_results[module.hub] = AuditHubResult(
                hub=module.hub,
                availability=AuditAvailability(status="not_available", evidence=module.fallback),
                findings=[{"severity": "warning", "message": module.fallback}],
            )
            warnings.append(module.fallback)
            continue

        module_objects = []
        module_errors: list[str] = []
        module_findings: list[dict[str, Any]] = []
        for object_type in module.object_types:
            module_objects.append(object_type)
            objects[object_type] = _audit_object(
                object_type,
                module,
                capabilities,
                connector=connector,
                depth=depth,
                sample_limit=sample_limit,
            )
            module_errors.extend(objects[object_type].availability.errors)
            module_findings.extend(objects[object_type].findings)

        if connector and not module.object_types:
            _probe_metadata_only_module(module, connector, module_errors, module_findings)
        elif not connector and not module.object_types:
            module_errors.append("Live enrichment disabled; metadata-only hub was not probed.")

        if connector and module.hub == "customization":
            try:
                custom_object_schemas = connector.get_object_schemas()
                if custom_object_schemas:
                    module_findings.append(
                        {
                            "severity": "info",
                            "type": "custom_objects_present",
                            "message": (
                                "Custom object schemas are present. V1 audits them but does not "
                                "plan custom-object writes."
                            ),
                            "count": len(custom_object_schemas),
                        }
                    )
            except HubSpotApiError as error:
                module_errors.append(str(error))

        status = _hub_status(objects, module, module_errors)
        hub_results[module.hub] = AuditHubResult(
            hub=module.hub,
            availability=AuditAvailability(
                status=status,
                evidence=_hub_evidence(module, status, module_errors),
                missing_scopes=list(module.required_scopes) if status == "not_available" else [],
                errors=module_errors,
            ),
            object_types=module_objects,
            endpoints=list(module.endpoints),
            findings=module_findings,
        )

    findings.extend(_global_findings(objects, custom_object_schemas))

    return CrmAudit(
        generated_at=utc_now_iso(),
        api_version=capabilities.api_version,
        depth=depth,
        hubs_requested=[item.strip() for item in hubs.split(",") if item.strip()] or ["auto"],
        hubs_selected=[module.hub for module in modules],
        capability_hash=stable_hash(capabilities),
        live_enrichment=connector is not None,
        sample_limit=sample_limit,
        hubs=hub_results,
        objects=objects,
        custom_object_schemas=_schema_summary(custom_object_schemas),
        findings=findings,
        warnings=warnings,
    )


def _audit_object(
    object_type: str,
    module: AuditModule,
    capabilities: PortalCapabilities,
    *,
    connector: HubSpotConnector | None,
    depth: str,
    sample_limit: int,
) -> AuditObjectMetadata:
    caps = capabilities.object_caps(object_type)
    errors: list[str] = list(caps.errors)
    properties_by_name = dict(caps.properties)
    property_groups: list[dict[str, Any]] = []
    pipelines = list(caps.pipelines)
    association_labels: list[dict[str, Any]] = []
    record_count: int | None = None
    sampled_count = 0

    if connector:
        try:
            properties_by_name = {
                item["name"]: item
                for item in connector.get_properties(object_type).get("results", [])
                if item.get("name")
            }
        except HubSpotApiError as error:
            errors.append(str(error))

        try:
            property_groups = connector.get_property_groups(object_type)
        except HubSpotApiError as error:
            errors.append(str(error))

        if object_type in module.pipelines_supported:
            try:
                pipelines = connector.get_pipelines(object_type)
            except HubSpotApiError as error:
                errors.append(str(error))

        if object_type in {"companies", "contacts", "deals"}:
            labels, label_errors = _association_labels_for_object(object_type, connector)
            association_labels = labels
            errors.extend(label_errors)

    property_metrics = _property_metrics(properties_by_name)
    pipeline_metrics = _pipeline_metrics(pipelines)

    if connector and depth == "metadata-quality" and properties_by_name:
        try:
            sample = connector.search_object_sample(
                object_type,
                properties=_sample_property_names(properties_by_name),
                limit=sample_limit,
            )
            record_count = sample.get("total")
            sampled_count = len(sample.get("results", []))
            _apply_sample_quality(property_metrics, sample.get("results", []), properties_by_name)
        except HubSpotApiError as error:
            errors.append(str(error))

    availability = _object_availability(caps.readable, bool(properties_by_name), errors)
    metadata = AuditObjectMetadata(
        object_type=object_type,
        availability=availability,
        property_count=len(properties_by_name),
        group_count=len(property_groups),
        pipeline_count=len(pipeline_metrics),
        association_label_count=len(association_labels),
        record_count=record_count,
        sampled_count=sampled_count,
        properties=property_metrics,
        property_groups=_property_group_summary(property_groups),
        pipelines=pipeline_metrics,
        association_labels=association_labels,
        quality={
            "sample_limit": sample_limit,
            "sampled_count": sampled_count,
            "record_count": record_count,
            "full_record_values_exported": False,
        },
        findings=[],
    )
    metadata.findings = _object_findings(metadata)
    return metadata


def _probe_metadata_only_module(
    module: AuditModule,
    connector: HubSpotConnector,
    errors: list[str],
    findings: list[dict[str, Any]],
) -> None:
    for endpoint in module.endpoints:
        if "{" in endpoint:
            continue
        try:
            payload = connector.get_metadata_endpoint(endpoint)
            count = (
                len(payload.get("results", []))
                if isinstance(payload.get("results"), list)
                else None
            )
            findings.append(
                {
                    "severity": "info",
                    "type": "metadata_endpoint_available",
                    "endpoint": endpoint,
                    "count": count,
                }
            )
        except HubSpotApiError as error:
            errors.append(str(error))


def _association_labels_for_object(
    object_type: str, connector: HubSpotConnector
) -> tuple[list[dict[str, Any]], list[str]]:
    labels: list[dict[str, Any]] = []
    errors: list[str] = []
    for from_type, to_type in COMMON_ASSOCIATION_PAIRS:
        if object_type not in {from_type, to_type}:
            continue
        try:
            for label in connector.get_association_labels(from_type, to_type):
                labels.append(
                    {
                        "from": from_type,
                        "to": to_type,
                        "label": label.get("label"),
                        "typeId": label.get("typeId"),
                        "category": label.get("category"),
                    }
                )
        except HubSpotApiError as error:
            errors.append(str(error))
    return labels, errors


def _property_metrics(properties_by_name: dict[str, dict[str, Any]]) -> list[AuditPropertyMetric]:
    metrics: list[AuditPropertyMetric] = []
    for name in sorted(properties_by_name):
        prop = properties_by_name[name]
        metrics.append(
            AuditPropertyMetric(
                name=name,
                label=prop.get("label"),
                type=prop.get("type"),
                field_type=prop.get("fieldType") or prop.get("field_type"),
                group_name=prop.get("groupName") or prop.get("group_name"),
                option_count=len(prop.get("options", []) or []),
                options=_option_summary(prop.get("options", []) or []),
            )
        )
    return metrics


def _pipeline_metrics(pipelines: list[dict[str, Any]]) -> list[AuditPipelineMetric]:
    metrics: list[AuditPipelineMetric] = []
    for pipeline in pipelines:
        stages = [
            AuditPipelineStage(
                id=stage.get("id"),
                label=stage.get("label", ""),
                display_order=stage.get("displayOrder"),
                metadata=stage.get("metadata") or {},
            )
            for stage in pipeline.get("stages", [])
        ]
        metrics.append(
            AuditPipelineMetric(
                id=pipeline.get("id"),
                label=pipeline.get("label", ""),
                display_order=pipeline.get("displayOrder"),
                stage_count=len(stages),
                stages=stages,
            )
        )
    return metrics


def _sample_property_names(properties_by_name: dict[str, dict[str, Any]]) -> list[str]:
    sortable = sorted(
        properties_by_name,
        key=lambda name: (
            properties_by_name[name].get("modificationMetadata", {}).get("readOnlyValue", False),
            name,
        ),
    )
    return sortable[:50]


def _apply_sample_quality(
    metrics: list[AuditPropertyMetric],
    sample_results: list[dict[str, Any]],
    properties_by_name: dict[str, dict[str, Any]],
) -> None:
    if not sample_results:
        return
    metric_by_name = {metric.name: metric for metric in metrics}
    filled = Counter()
    enum_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for record in sample_results:
        values = record.get("properties") or {}
        for name, value in values.items():
            if value not in (None, ""):
                filled[name] += 1
                prop = properties_by_name.get(name, {})
                if prop.get("type") == "enumeration":
                    enum_counts[name][str(value)] += 1

    denominator = len(sample_results)
    for name, count in filled.items():
        if metric := metric_by_name.get(name):
            metric.sample_fill_rate = round(count / denominator, 4)
    for name, counter in enum_counts.items():
        if metric := metric_by_name.get(name):
            metric.option_usage_counts = dict(counter)
    for metric in metrics:
        if metric.name in properties_by_name and metric.sample_fill_rate is None:
            metric.sample_fill_rate = 0.0


def _object_availability(
    preflight_readable: bool, has_properties: bool, errors: list[str]
) -> AuditAvailability:
    if has_properties:
        return AuditAvailability(
            status="partial" if errors and not preflight_readable else "available",
            evidence="Properties metadata was discovered.",
            errors=errors,
        )
    if preflight_readable and not errors:
        return AuditAvailability(status="partial", evidence="Object readable in preflight.")
    return AuditAvailability(
        status="not_available",
        evidence="Object metadata could not be discovered.",
        errors=errors,
    )


def _object_findings(metadata: AuditObjectMetadata) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    by_label: dict[str, list[AuditPropertyMetric]] = defaultdict(list)
    for prop in metadata.properties:
        normalized = _normalize_label(prop.label or prop.name)
        by_label[normalized].append(prop)

    for normalized, props in by_label.items():
        if len(props) < 2:
            continue
        shapes = {(prop.type, prop.field_type) for prop in props}
        finding_type = "conflicting_field_shapes" if len(shapes) > 1 else "duplicate_likely_fields"
        findings.append(
            {
                "severity": "warning",
                "type": finding_type,
                "object_type": metadata.object_type,
                "label_key": normalized,
                "properties": [prop.name for prop in props],
            }
        )

    for prop in metadata.properties:
        if prop.sample_fill_rate == 0.0 and metadata.sampled_count:
            findings.append(
                {
                    "severity": "info",
                    "type": "unused_field_in_sample",
                    "object_type": metadata.object_type,
                    "property": prop.name,
                    "sampled_count": metadata.sampled_count,
                }
            )

    if metadata.object_type in {"deals", "tickets"} and not metadata.pipelines:
        findings.append(
            {
                "severity": "warning",
                "type": "missing_pipeline_metadata",
                "object_type": metadata.object_type,
                "message": "No pipeline metadata was discovered for a pipeline-driven object.",
            }
        )
    return findings


def _global_findings(
    objects: dict[str, AuditObjectMetadata], custom_object_schemas: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for metadata in objects.values():
        findings.extend(metadata.findings)
    if custom_object_schemas:
        findings.append(
            {
                "severity": "info",
                "type": "custom_objects_gated",
                "message": "Custom objects exist but remain gated out of V1 planning.",
                "count": len(custom_object_schemas),
            }
        )
    return findings


def _hub_status(
    objects: dict[str, AuditObjectMetadata], module: AuditModule, errors: list[str]
) -> str:
    module_object_results = [objects[item] for item in module.object_types if item in objects]
    if not module.object_types:
        return "not_available" if errors else "partial"
    available = [
        item
        for item in module_object_results
        if item.availability.status in {"available", "partial"}
    ]
    if len(available) == len(module_object_results) and not errors:
        return "available"
    if available:
        return "partial"
    return "not_available"


def _hub_evidence(module: AuditModule, status: str, errors: list[str]) -> str:
    if status == "available":
        return "All declared audit surfaces were discovered."
    if status == "partial":
        return "Some declared audit surfaces were discovered; see errors for gaps."
    if errors:
        return errors[0]
    return module.fallback


def _property_group_summary(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": group.get("name"),
            "label": group.get("label"),
            "displayOrder": group.get("displayOrder"),
        }
        for group in groups
    ]


def _option_summary(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "label": option.get("label"),
            "value": option.get("value"),
            "hidden": bool(option.get("hidden", False)),
        }
        for option in options
    ]


def _schema_summary(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "objectTypeId": schema.get("objectTypeId"),
            "name": schema.get("name"),
            "labels": schema.get("labels"),
            "requiredProperties": schema.get("requiredProperties"),
            "searchableProperties": schema.get("searchableProperties"),
        }
        for schema in schemas
    ]


def _normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
