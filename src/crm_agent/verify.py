from __future__ import annotations

from crm_agent.hubspot import HubSpotConnector
from crm_agent.models import HubSpotManifest, ManifestOperation


def verify_manifest(manifest: HubSpotManifest, connector: HubSpotConnector) -> str:
    lines = [
        "# HubSpot Readback Report",
        "",
        f"- Manifest hash: `{manifest.manifest_hash}`",
        f"- Project slug: `{manifest.project_slug}`",
        "",
        "| Operation | Action | Status | Evidence |",
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
