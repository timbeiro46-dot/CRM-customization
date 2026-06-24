from __future__ import annotations

from collections import Counter
from pathlib import Path

from crm_agent.models import (
    HubSpotManifest,
    ManifestApproval,
    ManifestOperation,
    PortalCapabilities,
)
from crm_agent.validation import validate_manifest


def render_change_plan(
    *,
    manifest: HubSpotManifest,
    capabilities: PortalCapabilities,
    approval: ManifestApproval | None = None,
    manifest_path: Path = Path("hubspot_manifest.yaml"),
    capabilities_path: Path = Path("portal_capabilities.json"),
    approval_path: Path = Path("hubspot_manifest.approval.json"),
) -> str:
    report = validate_manifest(manifest, capabilities)
    approval_current = approval is not None and approval.manifest_hash == manifest.manifest_hash
    approval_status = (
        "aprobado por hash vigente"
        if approval_current
        else "pendiente de aprobacion por hash vigente"
    )
    applicability = (
        "aplicable para dry-run supervisado"
        if report.passed
        else "no aplicable hasta resolver errores de validacion"
    )
    planned = [
        item for item in manifest.operations if item.status == "planned" and item.action != "noop"
    ]
    noops = [item for item in manifest.operations if item.status == "noop" or item.action == "noop"]
    blocked = [item for item in manifest.operations if item.status == "blocked"]

    lines = [
        "# Revision humana antes de cambiar HubSpot",
        "",
        "## Lo importante",
        f"- Estado del plan: {applicability}",
        f"- Aprobacion: {approval_status}",
        f"- Manifest hash: `{manifest.manifest_hash}`",
        f"- Grupo de cambios nuevos: `{manifest.project_slug}`",
        f"- Cambios reales propuestos: {len(planned)}",
        f"- Elementos reutilizados o sin cambio: {len(noops)}",
        f"- Decisiones bloqueadas: {len(blocked)}",
        "",
        "## Decision requerida",
    ]
    if blocked:
        lines.append("- Resolver los bloqueos antes de aprobar este plan.")
    elif report.passed:
        lines.append(
            "- Revisar este plan. Si estas de acuerdo, el siguiente paso seguro es "
            "aprobar el hash y correr dry-run."
        )
    else:
        lines.append("- Corregir los errores de validacion antes de pedir aprobacion.")

    lines.extend(["", "## Validacion de seguridad"])
    if report.passed:
        lines.append("- Resultado: pasa.")
    else:
        lines.append("- Resultado: no pasa.")
    for error in report.errors:
        lines.append(f"- Error: {error}")
    for warning in report.warnings:
        lines.append(f"- Warning: {warning}")

    lines.extend(
        [
            "",
            "## Resumen por tipo de cambio",
        ]
    )
    for key, count in _operation_counts(manifest.operations).items():
        lines.append(f"- {key}: {count}")
    if not manifest.operations:
        lines.append("- No hay operaciones en el manifest.")

    lines.extend(["", "## Cambios que se simularan"])
    if planned:
        for operation in planned:
            lines.extend(_human_operation_lines(operation))
    else:
        lines.append("- No hay cambios planeados que escriban en HubSpot.")

    lines.extend(["", "## Reutilizado o sin cambios"])
    if noops:
        for operation in noops:
            lines.append(f"- `{operation.id}`: {_action_label(operation)}. {operation.reason}")
    else:
        lines.append("- No hay operaciones noop.")

    lines.extend(["", "## Bloqueos"])
    if blocked:
        for operation in blocked:
            lines.extend(_blocked_operation_lines(operation))
    else:
        lines.append("- Ningun bloqueo en el manifest.")

    lines.extend(
        [
            "",
            "## Gates antes de escribir",
            "- Este plan humano debe contener el hash actual del manifest.",
            "- `crm-agent validate --approve` debe pasar y aprobar ese hash.",
            "- `crm-agent apply` sin `--execute` debe generar `dry_run_report.md` vigente.",
            "- El usuario debe aprobar explicitamente `--execute` despues de revisar el dry-run.",
            "",
            "## Comandos supervisados",
            "Validar y aprobar el hash actual:",
            "",
            "```bash",
            (
                "crm-agent validate "
                f"--manifest {manifest_path} "
                f"--capabilities {capabilities_path} "
                "--approve"
            ),
            "```",
            "",
            "Dry-run obligatorio antes de escribir:",
            "",
            "```bash",
            f"crm-agent apply --manifest {manifest_path} --approval {approval_path}",
            "```",
            "",
            "Ese comando escribe `dry_run_report.md`; revisalo antes de aprobar `--execute`.",
            "",
            "Write real solo con aprobacion explicita del usuario:",
            "",
            "```bash",
            f"crm-agent apply --manifest {manifest_path} --approval {approval_path} --execute",
            "```",
            "",
            "## Regla de seguridad",
            (
                "No ejecutar `--execute` hasta que el usuario apruebe explicitamente este "
                "manifest hash y haya revisado el dry-run."
            ),
            "",
            "## Apendice tecnico",
            f"- Manifest: `{manifest_path}`",
            f"- Capacidades: `{capabilities_path}`",
            f"- Approval esperado: `{approval_path}`",
            f"- Version API: `{manifest.api_version}`",
        ]
    )
    for operation in planned:
        lines.extend(_technical_operation_lines(operation))
    return "\n".join(lines) + "\n"


def _operation_counts(operations: list[ManifestOperation]) -> dict[str, int]:
    counter = Counter(
        f"{operation.object_type} / {operation.action} / {operation.risk}"
        for operation in operations
    )
    return dict(sorted(counter.items()))


def _human_operation_lines(operation: ManifestOperation) -> list[str]:
    expected = ", ".join(f"{key}={value}" for key, value in operation.expected.items())
    lines = [
        f"- `{operation.id}`",
        f"  - Que haria: {_action_label(operation)} en {operation.object_type}.",
        f"  - Riesgo: {operation.risk}.",
        f"  - Resultado esperado: {expected or 'sin expectativa declarada'}.",
        f"  - Si algo sale mal: {operation.rollback}",
    ]
    if operation.reason:
        lines.append(f"  - Por que: {operation.reason}")
    return lines


def _blocked_operation_lines(operation: ManifestOperation) -> list[str]:
    return [
        f"- `{operation.id}`",
        f"  - Decision pendiente: {operation.reason}",
        "  - Siguiente paso: resolver este punto antes de aprobar o simular cambios.",
    ]


def _technical_operation_lines(operation: ManifestOperation) -> list[str]:
    lines = [
        f"- `{operation.id}`",
        f"  - Accion tecnica: {operation.action}",
        f"  - Metodo: {operation.method}",
        f"  - Endpoint: `{operation.endpoint}`",
    ]
    if operation.payload:
        lines.append(f"  - Payload keys: {', '.join(sorted(operation.payload.keys()))}")
    return lines


def _action_label(operation: ManifestOperation) -> str:
    labels = {
        "ensure_property": "crear propiedad",
        "extend_property_options": "extender opciones de propiedad",
        "ensure_pipeline": "crear pipeline",
        "ensure_pipeline_stage": "crear etapa de pipeline",
        "ensure_association_label": "crear etiqueta de asociacion",
        "noop": "sin cambio",
    }
    return labels.get(operation.action, operation.action)
