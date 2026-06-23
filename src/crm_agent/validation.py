from __future__ import annotations

from crm_agent.constants import BLOCKED_METHODS, STANDARD_PROPERTY_ALLOWLIST, SUPPORTED_OBJECTS
from crm_agent.io import stable_hash, utc_now_iso
from crm_agent.models import (
    HubSpotManifest,
    ManifestApproval,
    PortalCapabilities,
    ValidationReport,
)


def validate_manifest(
    manifest: HubSpotManifest,
    capabilities: PortalCapabilities,
    *,
    approve: bool = False,
    approved_by: str = "local_user",
) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = list(manifest.warnings)

    if manifest.api_version != capabilities.api_version:
        errors.append(
            f"Manifest API version {manifest.api_version} does not match capabilities "
            f"{capabilities.api_version}."
        )
    if manifest.capability_hash != stable_hash(capabilities):
        errors.append(
            "Manifest capability hash does not match the current capabilities file. "
            "Re-run plan before approving."
        )

    seen_ids: set[str] = set()
    for operation in manifest.operations:
        if operation.id in seen_ids:
            errors.append(f"Duplicate operation id: {operation.id}")
        seen_ids.add(operation.id)

        if operation.object_type not in SUPPORTED_OBJECTS:
            errors.append(f"{operation.id}: unsupported object type {operation.object_type}")
        if operation.method in BLOCKED_METHODS:
            errors.append(f"{operation.id}: DELETE is blocked in V1")
        if operation.endpoint.startswith("http"):
            errors.append(f"{operation.id}: endpoint must be relative")
        if operation.status == "blocked":
            errors.append(f"{operation.id}: blocked - {operation.reason}")
        if not operation.rollback:
            errors.append(f"{operation.id}: rollback note is required")
        if operation.action == "ensure_property":
            _validate_property_operation(operation, manifest.project_slug, errors, warnings)
        if operation.action == "ensure_pipeline" and operation.object_type != "deals":
            errors.append(f"{operation.id}: V1 only supports deal pipelines")

    approval = None
    passed = not errors
    if approve and passed:
        approval = ManifestApproval(
            manifest_hash=manifest.manifest_hash,
            approved_at=utc_now_iso(),
            approved_by=approved_by,
        )

    return ValidationReport(
        generated_at=utc_now_iso(),
        manifest_hash=manifest.manifest_hash,
        passed=passed,
        errors=errors,
        warnings=warnings,
        approval=approval,
    )


def _validate_property_operation(
    operation, project_slug: str, errors: list[str], warnings: list[str]
) -> None:
    name = operation.payload.get("name", "")
    standard = name in STANDARD_PROPERTY_ALLOWLIST.get(operation.object_type, set())
    if standard:
        warnings.append(f"{operation.id}: standard property mapping detected.")
        return
    if not name.startswith(f"{project_slug}_"):
        errors.append(
            f"{operation.id}: custom property '{name}' must start with namespace '{project_slug}_'."
        )
    if operation.payload.get("fieldType") == "calculation_equation":
        errors.append(f"{operation.id}: API-created calculation properties are gated out of V1.")
