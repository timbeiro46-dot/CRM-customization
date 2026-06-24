from __future__ import annotations

from crm_agent.hubspot import HubSpotConnector
from crm_agent.models import HubSpotManifest, ManifestOperation


def verify_manifest(manifest: HubSpotManifest, connector: HubSpotConnector) -> str:
    lines = [
        "# Evidencia final de HubSpot",
        "",
        "## En palabras simples",
        (
            "Este reporte lee HubSpot de vuelta y compara lo encontrado contra el plan "
            "aprobado. Es la evidencia de cierre del agente."
        ),
        "",
        "## Identidad del plan",
        f"- Manifest hash: `{manifest.manifest_hash}`",
        f"- Grupo de cambios nuevos: `{manifest.project_slug}`",
        "",
        "## Resultado por operacion",
        "",
        "| Operacion | Accion | Estado | Evidencia |",
        "| --- | --- | --- | --- |",
    ]
    for operation in manifest.operations:
        status, evidence = _verify_operation(operation, connector)
        lines.append(f"| `{operation.id}` | `{operation.action}` | {status} | {evidence} |")
    lines.append("")
    return "\n".join(lines)


def _verify_operation(operation: ManifestOperation, connector: HubSpotConnector) -> tuple[str, str]:
    if operation.action == "noop":
        return "skipped", operation.reason or "No change planned."
    if operation.action == "ensure_property":
        prop = connector.get_property(operation.object_type, operation.payload["name"])
        if prop:
            return "verified", f"Property `{operation.payload['name']}` exists."
        return "missing", f"Property `{operation.payload['name']}` was not found."
    if operation.action == "extend_property_options":
        prop = connector.get_property(operation.object_type, operation.payload["name"])
        if not prop:
            return "missing", f"Property `{operation.payload['name']}` was not found."
        existing_values = {
            str(item.get("value"))
            for item in prop.get("options", [])
            if item.get("value") is not None and not item.get("hidden")
        }
        missing = [
            item.get("value")
            for item in operation.payload.get("options_to_add", [])
            if str(item.get("value")) not in existing_values
        ]
        if missing:
            return "missing", f"Enum options still missing: `{', '.join(map(str, missing))}`."
        return "verified", f"Enum options exist on `{operation.payload['name']}`."
    if operation.action in {"ensure_pipeline", "ensure_pipeline_stage"}:
        label = operation.expected.get("pipeline_label") or operation.payload.get("label")
        for pipeline in connector.get_pipelines(operation.object_type):
            if pipeline.get("label", "").lower().strip() == str(label).lower().strip():
                if operation.action == "ensure_pipeline":
                    return "verified", f"Pipeline `{label}` exists."
                stage_label = operation.payload.get("label", "").lower().strip()
                for stage in pipeline.get("stages", []):
                    if stage.get("label", "").lower().strip() == stage_label:
                        return "verified", f"Stage `{operation.payload['label']}` exists."
                return (
                    "missing",
                    f"Pipeline exists but stage `{operation.payload['label']}` was not found.",
                )
        return "missing", f"Pipeline `{label}` was not found."
    return "unsupported", "No V1 readback verifier exists for this action."
