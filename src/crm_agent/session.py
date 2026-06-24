from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import ValidationError

from crm_agent.io import read_json, read_yaml, stable_hash, utc_now_iso, write_yaml
from crm_agent.models import (
    ArtifactSnapshot,
    BusinessContext,
    CrmAudit,
    CrmDesign,
    CrmReconciliation,
    HubSpotManifest,
    ManifestApproval,
    NextAction,
    PortalCapabilities,
    SessionState,
    SpecApproval,
)
from crm_agent.settings import load_dotenv

STATE_DIR = Path(".crm-agent")
SESSION_STATE_FILE = STATE_DIR / "session_state.yaml"
DISCOVERY_LEDGER_FILE = STATE_DIR / "discovery_ledger.md"
APPROVAL_LEDGER_FILE = STATE_DIR / "approval_ledger.md"
PROGRESS_FILE = STATE_DIR / "progress.md"

ARTIFACT_PATHS = {
    "capabilities": Path("portal_capabilities.json"),
    "audit": Path("crm_audit.yaml"),
    "business_context": Path("business_context.yaml"),
    "setup_spec": Path("crm_setup_spec.md"),
    "setup_spec_approval": Path("crm_setup_spec.approval.json"),
    "design": Path("crm_design.yaml"),
    "reconciliation": Path("crm_reconciliation.yaml"),
    "manifest": Path("hubspot_manifest.yaml"),
    "change_plan": Path("crm_change_plan.md"),
    "manifest_approval": Path("hubspot_manifest.approval.json"),
    "dry_run_report": Path("dry_run_report.md"),
    "apply_log": Path("apply_log.jsonl"),
    "readback_report": Path("readback_report.md"),
}


def build_session_state(root: Path = Path(".")) -> SessionState:
    token_configured = _token_configured(root)
    artifacts = _artifact_snapshots(root)
    spec_approved = _spec_approval_current(root, artifacts)
    reconciliation_current = _reconciliation_current(root, artifacts)
    manifest_approved = _manifest_approval_current(root, artifacts)
    change_plan_current = _change_plan_current(root, artifacts)
    dry_run_current = _dry_run_current(root, artifacts)
    readback_current = _readback_current(root, artifacts)
    blockers = _detect_blockers(
        root,
        artifacts,
        spec_approved=spec_approved,
        reconciliation_current=reconciliation_current,
        manifest_approved=manifest_approved,
    )
    business_summary = _business_summary(root, artifacts)
    discovery_complete = _discovery_complete(root, artifacts)
    pending_questions = _pending_discovery_questions(root, artifacts)

    phase = _determine_phase(
        token_configured=token_configured,
        artifacts=artifacts,
        blockers=blockers,
        discovery_complete=discovery_complete,
        spec_approved=spec_approved,
        reconciliation_current=reconciliation_current,
        manifest_approved=manifest_approved,
        change_plan_current=change_plan_current,
        dry_run_current=dry_run_current,
        readback_current=readback_current,
    )
    next_action = _next_action_for_phase(phase)
    return SessionState(
        generated_at=utc_now_iso(),
        phase=phase,
        token_configured=token_configured,
        artifacts=artifacts,
        blockers=blockers,
        business_summary=business_summary,
        pending_questions=pending_questions,
        completed_gates=_completed_gates(
            token_configured,
            artifacts,
            spec_approved,
            reconciliation_current,
            manifest_approved,
            change_plan_current,
            dry_run_current,
            readback_current,
        ),
        pending_gates=_pending_gates(
            phase,
            artifacts,
            spec_approved,
            reconciliation_current,
            manifest_approved,
            change_plan_current,
            dry_run_current,
            readback_current,
        ),
        next_action=next_action,
        safe_to_write=phase == "ready_to_apply",
    )


def persist_session_state(state: SessionState, root: Path = Path(".")) -> None:
    _ensure_state_files(root)
    write_yaml(root / SESSION_STATE_FILE, state)


def append_progress(message: str, root: Path = Path(".")) -> None:
    _ensure_state_files(root)
    with (root / PROGRESS_FILE).open("a", encoding="utf-8") as handle:
        handle.write(f"- {message}\n")


def append_approval_event(
    *,
    kind: str,
    artifact_path: Path,
    artifact_hash: str,
    approved_by: str,
    root: Path = Path("."),
) -> None:
    _ensure_state_files(root)
    with (root / APPROVAL_LEDGER_FILE).open("a", encoding="utf-8") as handle:
        handle.write(f"## {utc_now_iso()} - {kind}\n\n")
        handle.write(f"- Artifact: {artifact_path}\n")
        handle.write(f"- Hash: `{artifact_hash}`\n")
        handle.write(f"- Approved by: {approved_by}\n\n")


def format_session_summary(state: SessionState, *, technical: bool = False) -> str:
    lines = [
        "Estado del agente HubSpot",
        "",
        f"Fase actual: {state.next_action.title}",
        "",
        "Lo que ya puedo ver:",
    ]
    ready_items = _ready_items(state)
    lines.extend(f"- {item}" for item in ready_items)
    if state.business_summary:
        lines.append("")
        lines.append("Lo que entiendo del negocio:")
        lines.extend(f"- {item}" for item in state.business_summary)
    if state.completed_gates:
        lines.append("")
        lines.append("Controles ya cumplidos:")
        lines.extend(f"- {item}" for item in state.completed_gates)
    if state.pending_gates:
        lines.append("")
        lines.append("Controles pendientes:")
        lines.extend(f"- {item}" for item in state.pending_gates)
    if state.pending_questions and state.phase in {"discovery", "spec_review"}:
        lines.append("")
        lines.append("Preguntas utiles para continuar:")
        lines.extend(f"- {item}" for item in state.pending_questions[:5])
    if state.blockers:
        lines.append("")
        lines.append("Bloqueos que requieren decision humana:")
        lines.extend(f"- {item}" for item in state.blockers)
    lines.extend(
        [
            "",
            "Siguiente paso seguro:",
            f"- {state.next_action.description}",
        ]
    )
    if state.next_action.command:
        lines.append(f"- Comando sugerido: `{state.next_action.command}`")
    lines.extend(
        [
            "",
            "Regla de seguridad: no se escribira nada en HubSpot hasta tener manifest, "
            "validacion y aprobacion por hash.",
        ]
    )
    if technical:
        lines.append("")
        lines.append("Detalle tecnico de artefactos:")
        for name, artifact in state.artifacts.items():
            status = "presente" if artifact.exists else "pendiente"
            digest = f" ({artifact.hash[:12]})" if artifact.hash else ""
            lines.append(f"- {name}: {status} - {artifact.path}{digest}")
    return "\n".join(lines)


def _determine_phase(
    *,
    token_configured: bool,
    artifacts: dict[str, ArtifactSnapshot],
    blockers: list[str],
    discovery_complete: bool,
    spec_approved: bool,
    reconciliation_current: bool,
    manifest_approved: bool,
    change_plan_current: bool,
    dry_run_current: bool,
    readback_current: bool,
) -> str:
    if not token_configured:
        return "legacy_app_setup"
    if not artifacts["capabilities"].exists:
        return "preflight"
    if not artifacts["audit"].exists:
        return "audit"
    if not discovery_complete:
        return "discovery"
    if not artifacts["setup_spec"].exists or not spec_approved:
        return "spec_review"
    if not artifacts["design"].exists:
        return "design"
    if not artifacts["reconciliation"].exists or not reconciliation_current:
        return "reconcile"
    if not artifacts["manifest"].exists:
        return "plan"
    if not change_plan_current:
        return "plan_review"
    if blockers:
        return "blocked"
    if not artifacts["manifest_approval"].exists or not manifest_approved:
        return "validate"
    if not dry_run_current:
        return "dry_run"
    if artifacts["apply_log"].exists and not readback_current:
        return "verify"
    if not artifacts["apply_log"].exists:
        return "ready_to_apply"
    if readback_current:
        return "verified"
    return "verify"


def _next_action_for_phase(phase: str) -> NextAction:
    actions = {
        "legacy_app_setup": NextAction(
            id="setup_legacy_app",
            title="Configurar conexion segura",
            description=(
                "Crear la legacy private app, copiar el token a .env y volver a correr start."
            ),
            command="crm-agent setup-legacy-app",
        ),
        "preflight": NextAction(
            id="run_preflight",
            title="Leer capacidades del portal",
            description="Validar token, permisos, objetos y limites sin escribir en HubSpot.",
            command="crm-agent preflight --out portal_capabilities.json",
        ),
        "audit": NextAction(
            id="run_audit",
            title="Auditar el CRM actual",
            description=(
                "Inspeccionar configuracion existente y calidad agregada en modo read-only."
            ),
            command=(
                "crm-agent audit --capabilities portal_capabilities.json "
                "--out crm_audit.yaml --hubs auto --depth metadata-quality"
            ),
        ),
        "discovery": NextAction(
            id="run_discovery",
            title="Entender el negocio",
            description="Responder un discovery guiado para descubrir la ruta CRM adecuada.",
            command="crm-agent discover --audit crm_audit.yaml",
        ),
        "spec_review": NextAction(
            id="approve_spec",
            title="Revisar y aprobar el diagnostico",
            description=(
                "Revisar crm_setup_spec.md. Si esta correcto, aprobarlo antes de generar diseno."
            ),
            command="crm-agent approve-spec --spec crm_setup_spec.md",
        ),
        "design": NextAction(
            id="generate_design",
            title="Generar diseno CRM",
            description="Convertir el contexto aprobado en un diseno CRM seguro y revisable.",
            command=(
                "crm-agent design --context business_context.yaml "
                "--capabilities portal_capabilities.json --out crm_design.yaml"
            ),
        ),
        "reconcile": NextAction(
            id="run_reconcile",
            title="Reconciliar con HubSpot existente",
            description="Comparar el diseno contra el audit para reutilizar o bloquear conflictos.",
            command=(
                "crm-agent reconcile --design crm_design.yaml --audit crm_audit.yaml "
                "--out crm_reconciliation.yaml"
            ),
        ),
        "plan": NextAction(
            id="generate_manifest",
            title="Generar plan de cambios",
            description="Crear un manifest idempotente con riesgos y rollback, aun sin escribir.",
            command=(
                "crm-agent plan --design crm_design.yaml --capabilities portal_capabilities.json "
                "--reconciliation crm_reconciliation.yaml --out hubspot_manifest.yaml"
            ),
        ),
        "plan_review": NextAction(
            id="review_plan",
            title="Revisar plan humano",
            description=(
                "Traducir el manifest tecnico a un plan humano con riesgos, bloqueos, "
                "rollback y comandos supervisados."
            ),
            command=(
                "crm-agent review-plan --manifest hubspot_manifest.yaml "
                "--capabilities portal_capabilities.json --out crm_change_plan.md"
            ),
        ),
        "blocked": NextAction(
            id="resolve_blockers",
            title="Resolver conflictos",
            description="Resolver decisiones bloqueadas antes de validar o aplicar cambios.",
            command=None,
        ),
        "validate": NextAction(
            id="validate_manifest",
            title="Validar y aprobar manifest",
            description="Validar reglas de seguridad y aprobar el hash exacto del manifest.",
            command=(
                "crm-agent validate --manifest hubspot_manifest.yaml "
                "--capabilities portal_capabilities.json --approve"
            ),
        ),
        "dry_run": NextAction(
            id="dry_run_apply",
            title="Ejecutar dry-run supervisado",
            description=(
                "Simular el apply con el manifest aprobado y guardar evidencia revisable."
            ),
            command=(
                "crm-agent apply --manifest hubspot_manifest.yaml "
                "--approval hubspot_manifest.approval.json"
            ),
        ),
        "ready_to_apply": NextAction(
            id="execute_apply",
            title="Aplicar solo con aprobacion explicita",
            description=(
                "El dry-run vigente existe. Para escribir se requiere aprobacion explicita "
                "del usuario y usar --execute."
            ),
            command=(
                "crm-agent apply --manifest hubspot_manifest.yaml "
                "--approval hubspot_manifest.approval.json --execute"
            ),
            read_only=False,
            requires_human=True,
        ),
        "verify": NextAction(
            id="verify_readback",
            title="Verificar resultado",
            description="Leer HubSpot y producir reporte final de evidencia.",
            command="crm-agent verify --manifest hubspot_manifest.yaml --out readback_report.md",
        ),
        "verified": NextAction(
            id="review_readback",
            title="Revisar evidencia final",
            description="El readback existe; revisar readback_report.md y conservar artefactos.",
            command=None,
        ),
    }
    return actions[phase]


def _token_configured(root: Path) -> bool:
    load_dotenv(root / ".env")
    env_path = root / ".env"
    if not env_path.exists():
        return False
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("HUBSPOT_PRIVATE_APP_TOKEN="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            return bool(value and "REPLACE_ME" not in value)
    return False


def _artifact_snapshots(root: Path) -> dict[str, ArtifactSnapshot]:
    snapshots: dict[str, ArtifactSnapshot] = {}
    for name, relative_path in ARTIFACT_PATHS.items():
        path = root / relative_path
        snapshots[name] = ArtifactSnapshot(
            path=str(relative_path),
            exists=path.exists(),
            hash=_file_hash(path) if path.exists() else None,
        )
    return snapshots


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _spec_approval_current(root: Path, artifacts: dict[str, ArtifactSnapshot]) -> bool:
    if not artifacts["setup_spec"].exists or not artifacts["setup_spec_approval"].exists:
        return False
    try:
        approval = SpecApproval.model_validate(
            read_json(root / ARTIFACT_PATHS["setup_spec_approval"])
        )
    except (OSError, ValueError, ValidationError):
        return False
    return approval.spec_hash == artifacts["setup_spec"].hash


def _manifest_approval_current(root: Path, artifacts: dict[str, ArtifactSnapshot]) -> bool:
    if not artifacts["manifest"].exists or not artifacts["manifest_approval"].exists:
        return False
    try:
        manifest = HubSpotManifest.model_validate(read_yaml(root / ARTIFACT_PATHS["manifest"]))
        approval = ManifestApproval.model_validate(
            read_json(root / ARTIFACT_PATHS["manifest_approval"])
        )
    except (OSError, ValueError, ValidationError):
        return False
    return approval.manifest_hash == manifest.manifest_hash


def _reconciliation_current(root: Path, artifacts: dict[str, ArtifactSnapshot]) -> bool:
    required = ("capabilities", "audit", "design", "reconciliation")
    if any(not artifacts[name].exists for name in required):
        return False
    try:
        capabilities = PortalCapabilities.model_validate(
            read_json(root / ARTIFACT_PATHS["capabilities"])
        )
        audit = CrmAudit.model_validate(read_yaml(root / ARTIFACT_PATHS["audit"]))
        design = CrmDesign.model_validate(read_yaml(root / ARTIFACT_PATHS["design"]))
        reconciliation = CrmReconciliation.model_validate(
            read_yaml(root / ARTIFACT_PATHS["reconciliation"])
        )
    except (OSError, ValueError, ValidationError):
        return False
    return (
        reconciliation.design_hash == stable_hash(design)
        and reconciliation.audit_hash == audit.audit_hash
        and reconciliation.capability_hash == stable_hash(capabilities)
        and audit.capability_hash == stable_hash(capabilities)
    )


def _change_plan_current(root: Path, artifacts: dict[str, ArtifactSnapshot]) -> bool:
    if not artifacts["manifest"].exists or not artifacts["change_plan"].exists:
        return False
    try:
        manifest = HubSpotManifest.model_validate(read_yaml(root / ARTIFACT_PATHS["manifest"]))
        change_plan = (root / ARTIFACT_PATHS["change_plan"]).read_text(encoding="utf-8")
    except (OSError, ValueError, ValidationError):
        return False
    return f"Manifest hash: `{manifest.manifest_hash}`" in change_plan


def _dry_run_current(root: Path, artifacts: dict[str, ArtifactSnapshot]) -> bool:
    if not artifacts["manifest"].exists or not artifacts["dry_run_report"].exists:
        return False
    try:
        manifest = HubSpotManifest.model_validate(read_yaml(root / ARTIFACT_PATHS["manifest"]))
        report = (root / ARTIFACT_PATHS["dry_run_report"]).read_text(encoding="utf-8")
    except (OSError, ValueError, ValidationError):
        return False
    return f"Manifest hash: `{manifest.manifest_hash}`" in report


def _readback_current(root: Path, artifacts: dict[str, ArtifactSnapshot]) -> bool:
    if not artifacts["manifest"].exists or not artifacts["readback_report"].exists:
        return False
    try:
        manifest = HubSpotManifest.model_validate(read_yaml(root / ARTIFACT_PATHS["manifest"]))
        report = (root / ARTIFACT_PATHS["readback_report"]).read_text(encoding="utf-8")
    except (OSError, ValueError, ValidationError):
        return False
    return f"Manifest hash: `{manifest.manifest_hash}`" in report


def _detect_blockers(
    root: Path,
    artifacts: dict[str, ArtifactSnapshot],
    *,
    spec_approved: bool,
    reconciliation_current: bool,
    manifest_approved: bool,
) -> list[str]:
    blockers: list[str] = []
    if artifacts["setup_spec_approval"].exists and not spec_approved:
        blockers.append(
            "La aprobacion de crm_setup_spec.md no coincide con el archivo actual; "
            "hay que revisar y aprobar de nuevo."
        )
    if artifacts["reconciliation"].exists and reconciliation_current:
        try:
            reconciliation = CrmReconciliation.model_validate(
                read_yaml(root / ARTIFACT_PATHS["reconciliation"])
            )
            for decision in reconciliation.decisions:
                if decision.decision in {"blocked_conflict", "needs_review"}:
                    blockers.append(f"{decision.id}: {decision.decision} - {decision.reason}")
        except (OSError, ValueError, ValidationError) as error:
            blockers.append(f"No pude leer crm_reconciliation.yaml: {error}")
    if artifacts["manifest"].exists:
        try:
            manifest = HubSpotManifest.model_validate(read_yaml(root / ARTIFACT_PATHS["manifest"]))
            for operation in manifest.operations:
                if operation.status == "blocked":
                    blockers.append(f"{operation.id}: {operation.reason}")
        except (OSError, ValueError, ValidationError) as error:
            blockers.append(f"No pude leer hubspot_manifest.yaml: {error}")
    return blockers


def _business_summary(root: Path, artifacts: dict[str, ArtifactSnapshot]) -> list[str]:
    if not artifacts["business_context"].exists:
        return []
    try:
        context = BusinessContext.model_validate(
            read_yaml(root / ARTIFACT_PATHS["business_context"])
        )
    except (OSError, ValueError, ValidationError):
        return ["Hay un business_context.yaml, pero necesita revision porque no pude validarlo."]
    summary = [f"Empresa: {context.business_name}", f"Namespace: {context.project_slug}"]
    if context.industry:
        summary.append(f"Industria: {context.industry}")
    if context.sales_motion:
        summary.append(f"Movimiento comercial: {context.sales_motion}")
    if context.data_requirements:
        summary.append(f"Datos criticos identificados: {len(context.data_requirements)}")
    if context.reporting_goals:
        summary.append(f"Reportes esperados: {len(context.reporting_goals)}")
    return summary


def _discovery_complete(root: Path, artifacts: dict[str, ArtifactSnapshot]) -> bool:
    if not artifacts["business_context"].exists:
        return False
    try:
        context = BusinessContext.model_validate(
            read_yaml(root / ARTIFACT_PATHS["business_context"])
        )
    except (OSError, ValueError, ValidationError):
        return False
    placeholder = "Replace this with the user's sales process"
    has_process = bool(
        context.sales_process_notes and placeholder not in context.sales_process_notes
    )
    has_business_basics = bool(context.business_name and context.project_slug)
    has_goals = bool(context.reporting_goals or context.data_requirements or context.raw_notes)
    return has_business_basics and has_process and has_goals


def _pending_discovery_questions(
    root: Path, artifacts: dict[str, ArtifactSnapshot]
) -> list[str]:
    context = _read_business_context(root, artifacts)
    audit = _read_audit(root, artifacts)
    questions: list[str] = []

    if context is None:
        questions.extend(
            [
                "Cual es el resultado de negocio que quieres lograr con este CRM?",
                "Como entra, avanza y se cierra una oportunidad hoy?",
                "Que datos son obligatorios para calificar, priorizar o reportar una cuenta?",
            ]
        )
    else:
        if not context.sales_process_notes or "Replace this" in context.sales_process_notes:
            questions.append("Como es el proceso comercial real desde lead hasta cierre?")
        if not context.data_requirements:
            questions.append("Que campos o decisiones deben quedar visibles en HubSpot?")
        if not context.reporting_goals:
            questions.append("Que vistas, reportes o revisiones semanales necesita el equipo?")
        if not context.users:
            questions.append("Quienes usaran el CRM y que debe poder hacer cada rol?")

    if audit:
        has_existing_configuration = any(
            item.property_count or item.pipeline_count or item.association_label_count
            for item in audit.objects.values()
        )
        unavailable_hubs = [
            hub
            for hub, result in audit.hubs.items()
            if result.availability.status == "not_available"
        ]
        if has_existing_configuration:
            questions.append(
                "Que configuracion existente quieres conservar si reconcile la encuentra "
                "compatible?"
            )
        if unavailable_hubs:
            questions.append(
                "Hay hubs sin acceso confirmado; cuales son indispensables para este primer "
                "alcance?"
            )
    elif artifacts["capabilities"].exists:
        questions.append(
            "Antes de disenar conviene correr audit read-only para entender lo que ya existe."
        )

    return _dedupe(questions)


def _read_business_context(
    root: Path, artifacts: dict[str, ArtifactSnapshot]
) -> BusinessContext | None:
    if not artifacts["business_context"].exists:
        return None
    try:
        return BusinessContext.model_validate(read_yaml(root / ARTIFACT_PATHS["business_context"]))
    except (OSError, ValueError, ValidationError):
        return None


def _read_audit(root: Path, artifacts: dict[str, ArtifactSnapshot]) -> CrmAudit | None:
    if not artifacts["audit"].exists:
        return None
    try:
        return CrmAudit.model_validate(read_yaml(root / ARTIFACT_PATHS["audit"]))
    except (OSError, ValueError, ValidationError):
        return None


def _completed_gates(
    token_configured: bool,
    artifacts: dict[str, ArtifactSnapshot],
    spec_approved: bool,
    reconciliation_current: bool,
    manifest_approved: bool,
    change_plan_current: bool,
    dry_run_current: bool,
    readback_current: bool,
) -> list[str]:
    gates: list[str] = []
    if token_configured:
        gates.append("Conexion local configurada")
    if artifacts["capabilities"].exists:
        gates.append("Preflight de capacidades guardado")
    if artifacts["audit"].exists:
        gates.append("Audit profundo read-only guardado")
    if artifacts["business_context"].exists:
        gates.append("Discovery persistido en business_context.yaml")
    if artifacts["setup_spec"].exists and spec_approved:
        gates.append("Diagnostico humano aprobado por hash vigente")
    if artifacts["reconciliation"].exists and reconciliation_current:
        gates.append("Reconciliacion contra lo existente vigente")
    if artifacts["change_plan"].exists and change_plan_current:
        gates.append("Plan humano de cambios vigente")
    if artifacts["manifest"].exists and manifest_approved:
        gates.append("Manifest validado y aprobado por hash vigente")
    if artifacts["dry_run_report"].exists and dry_run_current:
        gates.append("Dry-run vigente documentado")
    if artifacts["apply_log"].exists:
        gates.append("Apply log de escritura presente")
    if artifacts["readback_report"].exists and readback_current:
        gates.append("Readback de HubSpot documentado")
    return gates


def _pending_gates(
    phase: str,
    artifacts: dict[str, ArtifactSnapshot],
    spec_approved: bool,
    reconciliation_current: bool,
    manifest_approved: bool,
    change_plan_current: bool,
    dry_run_current: bool,
    readback_current: bool,
) -> list[str]:
    gates_by_phase = {
        "legacy_app_setup": ["Crear legacy private app y guardar token local en .env"],
        "preflight": ["Preflight read-only de permisos, objetos y limites"],
        "audit": ["Audit profundo del portal y calidad agregada"],
        "discovery": ["Discovery adaptativo de negocio antes de disenar"],
        "spec_review": ["Revision humana de crm_setup_spec.md y aprobacion por hash"],
        "design": ["Diseno CRM generado desde el spec aprobado"],
        "reconcile": ["Reconciliacion del diseno con configuracion existente"],
        "plan": ["Manifest idempotente con riesgos, rollback y blockers"],
        "plan_review": ["Plan humano vigente para revisar cambios, riesgos y rollback"],
        "blocked": ["Resolver conflictos humanos antes de validar"],
        "validate": ["Validacion de seguridad y aprobacion del manifest por hash"],
        "dry_run": ["Dry-run persistente antes de cualquier --execute"],
        "ready_to_apply": ["Aprobacion humana explicita para ejecutar --execute"],
        "verify": ["Readback final contra HubSpot y reporte de evidencia"],
        "verified": ["Revisar y conservar evidencia final"],
    }
    gates = list(gates_by_phase.get(phase, []))
    if artifacts["setup_spec_approval"].exists and not spec_approved:
        gates.append("Reaprobar crm_setup_spec.md porque el hash cambio")
    if artifacts["reconciliation"].exists and not reconciliation_current:
        gates.append(
            "Regenerar crm_reconciliation.yaml porque design, audit o capabilities cambiaron"
        )
    if artifacts["manifest_approval"].exists and not manifest_approved:
        gates.append("Revalidar hubspot_manifest.yaml porque el hash cambio")
    if artifacts["change_plan"].exists and not change_plan_current:
        gates.append("Regenerar crm_change_plan.md porque el manifest cambio")
    if artifacts["dry_run_report"].exists and not dry_run_current:
        gates.append("Regenerar dry_run_report.md porque el manifest cambio")
    if artifacts["readback_report"].exists and not readback_current:
        gates.append("Regenerar readback_report.md porque el manifest cambio")
    return _dedupe(gates)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _ready_items(state: SessionState) -> list[str]:
    items = []
    if state.token_configured:
        items.append("Token local configurado en .env")
    else:
        items.append("Falta configurar el token local de HubSpot")
    for name, label in [
        ("capabilities", "Preflight del portal"),
        ("audit", "Audit read-only"),
        ("business_context", "Discovery de negocio"),
        ("setup_spec", "Diagnostico humano"),
        ("design", "Diseno CRM"),
        ("reconciliation", "Reconciliacion"),
        ("manifest", "Manifest de cambios"),
        ("change_plan", "Plan humano de cambios"),
        ("manifest_approval", "Aprobacion por hash"),
        ("dry_run_report", "Reporte de dry-run"),
        ("apply_log", "Log de apply"),
        ("readback_report", "Reporte de verificacion"),
    ]:
        if state.artifacts[name].exists:
            items.append(f"{label}: listo")
    return items


def _ensure_state_files(root: Path) -> None:
    state_dir = root / STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    progress = root / PROGRESS_FILE
    if not progress.exists():
        progress.write_text("# CRM Agent Progress\n\n", encoding="utf-8")
    ledger = root / DISCOVERY_LEDGER_FILE
    if not ledger.exists():
        ledger.write_text("# CRM Discovery Ledger\n\n", encoding="utf-8")
    approvals = root / APPROVAL_LEDGER_FILE
    if not approvals.exists():
        approvals.write_text("# CRM Approval Ledger\n\n", encoding="utf-8")
