from __future__ import annotations

from pathlib import Path
from typing import Any

from crm_agent.errors import ApprovalError, HubSpotApiError
from crm_agent.hubspot import HubSpotConnector
from crm_agent.io import append_jsonl, redact, utc_now_iso
from crm_agent.models import HubSpotManifest, ManifestApproval, ManifestOperation


def assert_approval(manifest: HubSpotManifest, approval: ManifestApproval) -> None:
    if manifest.manifest_hash != approval.manifest_hash:
        raise ApprovalError(
            "Approval hash does not match the current manifest. Re-run validate --approve."
        )


def apply_manifest(
    *,
    manifest: HubSpotManifest,
    approval: ManifestApproval,
    connector: HubSpotConnector,
    log_path: Path,
    execute: bool = False,
) -> list[dict[str, Any]]:
    assert_approval(manifest, approval)
    results: list[dict[str, Any]] = []
    for operation in manifest.operations:
        if operation.status != "planned" or operation.action == "noop":
            results.append(
                _event(operation, "skipped", {"reason": operation.reason or operation.status})
            )
            continue
        if not execute:
            results.append(_event(operation, "dry_run", {"payload": operation.payload}))
            continue
        try:
            result = connector.apply_operation(operation)
            event = _event(operation, result.get("status", "applied"), result)
        except HubSpotApiError as error:
            event = _event(operation, "failed", {"error": str(error)})
        append_jsonl(log_path, redact(event))
        results.append(event)
    return results


def dry_run_manifest(
    *, manifest: HubSpotManifest, approval: ManifestApproval
) -> list[dict[str, Any]]:
    assert_approval(manifest, approval)
    return [
        _event(
            operation,
            _dry_run_status(operation),
            {
                "endpoint": operation.endpoint,
                "risk": operation.risk,
                "expected": operation.expected,
                "rollback": operation.rollback,
                "reason": operation.reason,
                "payload": operation.payload,
            },
        )
        for operation in manifest.operations
    ]


def _dry_run_status(operation: ManifestOperation) -> str:
    return "dry_run" if operation.status == "planned" and operation.action != "noop" else "skipped"


def render_dry_run_report(
    *,
    manifest: HubSpotManifest,
    approval: ManifestApproval,
    results: list[dict[str, Any]],
    manifest_path: Path = Path("hubspot_manifest.yaml"),
    approval_path: Path = Path("hubspot_manifest.approval.json"),
) -> str:
    approved = approval.manifest_hash == manifest.manifest_hash
    dry_run_count = sum(1 for item in results if item["status"] == "dry_run")
    skipped_count = sum(1 for item in results if item["status"] == "skipped")
    lines = [
        "# Dry-run supervisado HubSpot",
        "",
        "## En palabras simples",
        (
            "Este reporte simulo el plan aprobado. No escribio en HubSpot y sirve "
            "para decidir si se autoriza el `--execute` real."
        ),
        "",
        "## Resumen",
        f"- Manifest: `{manifest_path}`",
        f"- Approval: `{approval_path}`",
        f"- Manifest hash: `{manifest.manifest_hash}`",
        f"- Aprobacion vigente: {'si' if approved else 'no'}",
        f"- Operaciones simuladas: {dry_run_count}",
        f"- Operaciones omitidas: {skipped_count}",
        "",
        "## Resultado por operacion",
    ]
    for item in results:
        details = item.get("details", {})
        lines.extend(
            [
                f"- `{item['operation_id']}`",
                f"  - Accion tecnica: {item['action']}",
                f"  - Objeto: {item['object_type']}",
                f"  - Estado: {item['status']}",
                f"  - Riesgo: {details.get('risk', 'n/a')}",
                f"  - Esperado: {details.get('expected') or 'n/a'}",
                f"  - Rollback: {details.get('rollback') or 'n/a'}",
            ]
        )
        if details.get("reason"):
            lines.append(f"  - Razon: {details['reason']}")
    lines.extend(
        [
            "",
            "## Gate de escritura",
            (
                "Este reporte solo permite pedir aprobacion humana para `--execute`; "
                "no autoriza escritura por si mismo."
            ),
            "",
            "## Apendice tecnico",
        ]
    )
    for item in results:
        details = item.get("details", {})
        lines.append(
            f"- `{item['operation_id']}` -> `{details.get('endpoint', 'n/a')}`"
        )
    return "\n".join(lines) + "\n"


def dry_run_report_current(report_path: Path, manifest: HubSpotManifest) -> bool:
    if not report_path.exists():
        return False
    return f"Manifest hash: `{manifest.manifest_hash}`" in report_path.read_text(encoding="utf-8")


def _event(operation: ManifestOperation, status: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": utc_now_iso(),
        "operation_id": operation.id,
        "action": operation.action,
        "object_type": operation.object_type,
        "status": status,
        "details": details,
    }
