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


def _event(operation: ManifestOperation, status: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": utc_now_iso(),
        "operation_id": operation.id,
        "action": operation.action,
        "object_type": operation.object_type,
        "status": status,
        "details": details,
    }
