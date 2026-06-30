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

GUIDED_ROUTE = [
    ("Conectar", "preparar acceso local seguro"),
    ("Leer", "entender permisos, objetos y plan disponible"),
    ("Descubrir", "entender el negocio y lo que ya existe"),
    ("Disenar", "proponer una ruta CRM sin escribir nada"),
    ("Revisar", "traducir cambios a lenguaje humano"),
    ("Simular", "hacer una simulacion obligatoria"),
    ("Aplicar", "escribir solo con aprobacion explicita"),
    ("Verificar", "leer HubSpot de vuelta y cerrar con evidencia"),
]

PHASE_EXPERIENCE = {
    "legacy_app_setup": {
        "route": "Conectar",
        "title": "Fase 1 - Conexion segura",
        "plain": (
            "Primero verifico si ya tenemos acceso seguro a HubSpot. Sin ese acceso "
            "no puedo revisar tu portal ni debo inventar lo que se puede hacer."
        ),
        "agent": "Te guia paso a paso para crear una conexion privada de HubSpot.",
        "human": "Estar con un super admin de HubSpot para crear la clave de acceso.",
        "safety": "Todavia no hay llamadas al portal ni escrituras.",
    },
    "preflight": {
        "route": "Leer",
        "title": "Fase 2 - Lectura del portal",
        "plain": (
            "Ya hay acceso seguro. Ahora confirmo que puedo leer permisos, datos "
            "principales y limites antes de pedirte decisiones de negocio."
        ),
        "agent": "Hace una primera lectura segura del portal.",
        "human": "Confirmar que este es el portal correcto.",
        "safety": "La primera lectura no escribe en HubSpot.",
    },
    "audit": {
        "route": "Leer",
        "title": "Fase 2 - Audit del CRM existente",
        "plain": (
            "Necesito ver que configuracion ya existe para no duplicar propiedades, "
            "pipelines o decisiones que el equipo ya usa."
        ),
        "agent": "Revisa la configuracion existente y senales agregadas de calidad.",
        "human": "No necesita decidir todavia; solo confirmar que se puede leer el portal.",
        "safety": "Esta revision solo lee informacion agregada y no cambia HubSpot.",
    },
    "discovery": {
        "route": "Descubrir",
        "title": "Fase 3 - Discovery guiado",
        "plain": (
            "Aqui convierto el proceso comercial en una ruta CRM. Pregunto de a una "
            "decision estrategica para evitar un formulario tecnico."
        ),
        "agent": "Hace preguntas de negocio y adapta el alcance al audit disponible.",
        "human": "Responder la siguiente pregunta con lenguaje normal.",
        "safety": "Discovery solo guarda contexto local y no cambia HubSpot.",
    },
    "spec_review": {
        "route": "Descubrir",
        "title": "Fase 3 - Revision del diagnostico",
        "plain": (
            "Ya existe un diagnostico humano. Antes de disenar cambios, confirmamos "
            "que representa el negocio real."
        ),
        "agent": "Resume el diagnostico y marca preguntas o bloqueos.",
        "human": "Aprobar el diagnostico solo si representa el negocio.",
        "safety": "Sin aprobar el diagnostico no se avanza a proponer cambios.",
    },
    "design": {
        "route": "Disenar",
        "title": "Fase 4 - Diseno CRM",
        "plain": (
            "Transformo el diagnostico aprobado en una propuesta CRM revisable, todavia "
            "sin tocar HubSpot."
        ),
        "agent": "Genera propiedades, pipeline y supuestos desde el contexto aprobado.",
        "human": "Revisar si el diseno refleja el proceso real.",
        "safety": "El comando falla si el diagnostico aprobado esta desactualizado.",
    },
    "reconcile": {
        "route": "Disenar",
        "title": "Fase 4 - Reconciliacion con lo existente",
        "plain": (
            "Comparo la propuesta contra el portal actual para reutilizar lo compatible "
            "y bloquear coincidencias dudosas."
        ),
        "agent": "Decide reutilizar, crear, extender o pedir decision humana.",
        "human": "Resolver conflictos cuando el portal tenga algo parecido.",
        "safety": "No sobrescribe configuracion existente automaticamente.",
    },
    "plan": {
        "route": "Revisar",
        "title": "Fase 5 - Plan de cambios",
        "plain": (
            "Convierto la propuesta revisada en un plan exacto de cambios, con riesgos "
            "y salida manual si algo no conviene, pero aun sin escribir."
        ),
        "agent": "Genera el plan de cambios desde hechos actuales.",
        "human": "Esperar la version humana del plan antes de aprobar.",
        "safety": "El plan sigue bloqueado hasta revision y aprobacion humana.",
    },
    "plan_review": {
        "route": "Revisar",
        "title": "Fase 5 - Revision humana",
        "plain": (
            "El plan debe verse como una pagina clara: que cambiaria, que se conserva, "
            "riesgos, salida manual y bloqueos."
        ),
        "agent": "Produce una version humana para revisar sin lenguaje tecnico.",
        "human": "Leer el plan humano y pedir ajustes si algo no cuadra.",
        "safety": "No se puede aprobar nada si el plan humano esta desactualizado.",
    },
    "blocked": {
        "route": "Revisar",
        "title": "Fase bloqueada - Decision humana",
        "plain": "Hay conflictos o ambiguedades que no debo resolver solo.",
        "agent": "Muestra el conflicto concreto y espera una decision.",
        "human": "Elegir conservar, crear nuevo, extender o ajustar el alcance.",
        "safety": "Mientras haya blockers, no hay validacion ni apply.",
    },
    "validate": {
        "route": "Revisar",
        "title": "Fase 5 - Aprobacion del plan",
        "plain": (
            "Valido reglas de seguridad y, si todo pasa, dejo aprobado exactamente el "
            "plan que se va a simular."
        ),
        "agent": "Comprueba el plan contra la lectura actual y el plan humano vigente.",
        "human": "Aprobar solo despues de revisar el plan.",
        "safety": "La aprobacion caduca si el plan cambia.",
    },
    "dry_run": {
        "route": "Simular",
        "title": "Fase 6 - Simulacion obligatoria",
        "plain": (
            "Antes de escribir, simulo cada cambio y dejo un reporte revisable de "
            "lo que pasaria."
        ),
        "agent": "Genera un reporte de simulacion.",
        "human": "Revisar la simulacion antes de autorizar escritura real.",
        "safety": "La simulacion no escribe en HubSpot.",
    },
    "ready_to_apply": {
        "route": "Aplicar",
        "title": "Fase 7 - Escritura aprobada",
        "plain": (
            "Todo esta listo, pero escribir en HubSpot requiere una aprobacion humana "
            "explicita para aplicar."
        ),
        "agent": "Puede ejecutar solo si el usuario aprueba ese paso exacto.",
        "human": "Decir explicitamente que aprueba aplicar los cambios reales.",
        "safety": "Sin esa aprobacion, el agente se detiene.",
    },
    "verify": {
        "route": "Verificar",
        "title": "Fase 8 - Verificacion",
        "plain": "Despues de escribir, leo HubSpot de vuelta y comparo contra el plan.",
        "agent": "Genera evidencia final.",
        "human": "Revisar la evidencia final.",
        "safety": "La entrega no se considera cerrada sin verificacion vigente.",
    },
    "verified": {
        "route": "Verificar",
        "title": "Fase 8 - Cierre con evidencia",
        "plain": "La evidencia final coincide con el plan actual.",
        "agent": "Resume resultados desde la verificacion.",
        "human": "Conservar los artefactos y decidir siguientes mejoras.",
        "safety": "Cualquier cambio nuevo vuelve a pasar por revision y simulacion.",
    },
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
    experience = PHASE_EXPERIENCE[state.phase]
    lines = [
        "Hola, soy tu agente de configuracion CRM.",
        "",
        "Primero necesitamos conectar HubSpot de forma segura para poder revisar tu portal.",
        f"Estado actual: {_connection_status(state)}",
        "Si no esta conectado, te guio paso a paso.",
        "No voy a cambiar nada en HubSpot sin mostrarte un plan claro y pedirte aprobacion.",
        "",
        "Agente CRM guiado",
        "",
        _route_line(state.phase),
        "",
        experience["title"],
        experience["plain"],
        "",
        "Rol del agente:",
        f"- {experience['agent']}",
        "",
        "Rol humano:",
        f"- {experience['human']}",
        "",
        "Estado visible:",
    ]
    ready_items = _ready_items(state)
    lines.extend(f"- {item}" for item in ready_items)
    if state.business_summary:
        lines.append("")
        lines.append("Lo que entiendo del negocio:")
        lines.extend(f"- {item}" for item in state.business_summary)
    if state.completed_gates:
        lines.append("")
        lines.append("Listo:")
        lines.extend(f"- {item}" for item in state.completed_gates)
    if state.pending_gates:
        lines.append("")
        lines.append("Falta:")
        lines.extend(f"- {item}" for item in state.pending_gates)
    if state.pending_questions and state.phase in {"discovery", "spec_review", "blocked"}:
        lines.append("")
        lines.append("Pregunta estrategica ahora:")
        lines.append(f"- {state.pending_questions[0]}")
        if len(state.pending_questions) > 1 and technical:
            lines.append("")
            lines.append("Preguntas siguientes:")
            lines.extend(f"- {item}" for item in state.pending_questions[1:5])
    if state.blockers:
        lines.append("")
        lines.append("Bloqueos que requieren decision humana:")
        lines.extend(f"- {item}" for item in state.blockers)
    lines.extend(
        [
            "",
            "Siguiente paso guiado:",
            f"- {state.next_action.description}",
        ]
    )
    if state.phase == "legacy_app_setup" and not state.token_configured:
        lines.extend(
            [
                "",
                "Para crear el acceso seguro:",
                "- Necesitas estar con un super admin de HubSpot.",
                "- Vamos a crear una conexion privada.",
                "- HubSpot te dara una clave.",
                "- Esa clave se guarda localmente; no me la pegues en el chat.",
                "- Cuando este guardada, yo verifico si puedo leer el portal.",
            ]
        )
    if state.next_action.command and technical:
        lines.append(f"- Comando sugerido: `{state.next_action.command}`")
    lines.extend(
        [
            "",
            "Seguridad:",
            f"- {experience['safety']}",
            (
                "- No voy a cambiar nada en HubSpot sin mostrarte el plan, simularlo "
                "y pedirte aprobacion explicita."
            ),
        ]
    )
    if technical:
        lines.append(
            "- Regla tecnica: no ejecutar `crm-agent apply --execute` hasta tener "
            "manifest validado, aprobacion por hash y dry-run vigente."
        )
        lines.append("")
        lines.append("Detalle tecnico de artefactos:")
        for name, artifact in state.artifacts.items():
            status = "presente" if artifact.exists else "pendiente"
            digest = f" ({artifact.hash[:12]})" if artifact.hash else ""
            lines.append(f"- {name}: {status} - {artifact.path}{digest}")
    return "\n".join(lines)


def _connection_status(state: SessionState) -> str:
    if state.token_configured:
        return (
            "ya tenemos acceso seguro a HubSpot. Primero voy a revisar que permisos "
            "y configuracion existen."
        )
    return "todavia no tenemos acceso seguro a HubSpot."


def _route_line(phase: str) -> str:
    current_route = PHASE_EXPERIENCE[phase]["route"]
    parts = []
    for label, _description in GUIDED_ROUTE:
        marker = "*" if label == current_route else "-"
        parts.append(f"{marker} {label}")
    return "Ruta: " + " > ".join(parts)


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
                "Preparar el acceso local para que pueda leer el portal correcto sin "
                "guardar secretos en documentos compartidos."
            ),
            command="crm-agent setup-legacy-app",
        ),
        "preflight": NextAction(
            id="run_preflight",
            title="Leer capacidades del portal",
            description=(
                "Confirmar que puedo leer objetos, permisos y limites del portal antes de "
                "pedir decisiones de negocio."
            ),
            command="crm-agent preflight --out portal_capabilities.json",
        ),
        "audit": NextAction(
            id="run_audit",
            title="Auditar el CRM actual",
            description=(
                "Revisar configuracion existente y calidad agregada para conservar lo que "
                "ya funciona."
            ),
            command=(
                "crm-agent audit --capabilities portal_capabilities.json "
                "--out crm_audit.yaml --hubs auto --depth metadata-quality"
            ),
        ),
        "discovery": NextAction(
            id="run_discovery",
            title="Entender el negocio",
            description=(
                "Responder la siguiente pregunta de negocio para construir una ruta CRM "
                "adaptada al portal real."
            ),
            command="crm-agent discover --audit crm_audit.yaml",
        ),
        "spec_review": NextAction(
            id="approve_spec",
            title="Revisar y aprobar el diagnostico",
            description=(
                "Revisar el diagnostico humano. Si representa el negocio, aprobarlo "
                "antes del diseno."
            ),
            command="crm-agent approve-spec --spec crm_setup_spec.md",
        ),
        "design": NextAction(
            id="generate_design",
            title="Generar diseno CRM",
            description=(
                "Convertir el diagnostico aprobado en una propuesta CRM revisable, sin "
                "escribir en HubSpot."
            ),
            command=(
                "crm-agent design --context business_context.yaml "
                "--capabilities portal_capabilities.json --out crm_design.yaml"
            ),
        ),
        "reconcile": NextAction(
            id="run_reconcile",
            title="Reconciliar con HubSpot existente",
            description=(
                "Comparar la propuesta contra el portal para reutilizar assets compatibles "
                "y bloquear ambiguedades."
            ),
            command=(
                "crm-agent reconcile --design crm_design.yaml --audit crm_audit.yaml "
                "--out crm_reconciliation.yaml"
            ),
        ),
        "plan": NextAction(
            id="generate_manifest",
            title="Generar plan de cambios",
            description=(
                "Crear el plan exacto de cambios, riesgos y salida manual, todavia sin "
                "escribir en HubSpot."
            ),
            command=(
                "crm-agent plan --design crm_design.yaml --capabilities portal_capabilities.json "
                "--reconciliation crm_reconciliation.yaml --out hubspot_manifest.yaml"
            ),
        ),
        "plan_review": NextAction(
            id="review_plan",
            title="Revisar plan humano",
            description=(
                "Traducir el plan a una revision humana clara: que cambiaria, "
                "que se reutiliza, riesgos, bloqueos y salida manual."
            ),
            command=(
                "crm-agent review-plan --manifest hubspot_manifest.yaml "
                "--capabilities portal_capabilities.json --out crm_change_plan.md"
            ),
        ),
        "blocked": NextAction(
            id="resolve_blockers",
            title="Resolver conflictos",
            description=(
                "Tomar la decision de negocio indicada en los blockers antes de validar "
                "cualquier cambio."
            ),
            command=None,
        ),
        "validate": NextAction(
            id="validate_manifest",
            title="Validar y aprobar plan",
            description=(
                "Validar reglas de seguridad y aprobar solo el plan exacto que ya tiene "
                "revision humana vigente."
            ),
            command=(
                "crm-agent validate --manifest hubspot_manifest.yaml "
                "--capabilities portal_capabilities.json --approve"
            ),
        ),
        "dry_run": NextAction(
            id="dry_run_apply",
            title="Ejecutar simulacion supervisada",
            description=(
                "Simular el plan aprobado y guardar evidencia revisable antes de pedir "
                "cualquier escritura real."
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
                "La simulacion vigente existe. La escritura real solo procede si el "
                "usuario aprueba explicitamente aplicar."
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
            description="Leer HubSpot de vuelta y producir evidencia final contra el plan.",
            command="crm-agent verify --manifest hubspot_manifest.yaml --out readback_report.md",
        ),
        "verified": NextAction(
            id="review_readback",
            title="Revisar evidencia final",
            description=(
                "La verificacion vigente existe; revisar la evidencia final del cambio."
            ),
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
            "La aprobacion anterior del diagnostico ya no coincide con la version actual; "
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
            blockers.append(f"No pude leer la comparacion con lo existente: {error}")
    if artifacts["manifest"].exists:
        try:
            manifest = HubSpotManifest.model_validate(read_yaml(root / ARTIFACT_PATHS["manifest"]))
            for operation in manifest.operations:
                if operation.status == "blocked":
                    blockers.append(f"{operation.id}: {operation.reason}")
        except (OSError, ValueError, ValidationError) as error:
            blockers.append(f"No pude leer el plan tecnico de cambios: {error}")
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
    summary = [f"Empresa: {context.business_name}", f"Grupo de cambios: {context.project_slug}"]
    if context.industry:
        summary.append(f"Industria: {context.industry}")
    if context.sales_motion:
        summary.append(f"Movimiento comercial: {context.sales_motion}")
    if context.data_requirements:
        summary.append(f"Datos criticos identificados: {len(context.data_requirements)}")
    if context.reporting_goals:
        summary.append(f"Reportes esperados: {len(context.reporting_goals)}")
    if context.source_documents:
        summary.append(f"Fuentes de contexto aportadas: {len(context.source_documents)}")
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
                "Tienes pagina web, Excel, CSV o documento donde ya este explicado el "
                "proceso comercial actual?",
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
        if not context.source_documents:
            questions.append(
                "Tienes pagina web, Excel, CSV o documento donde ya este explicado el "
                "proceso comercial actual?"
            )

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
        gates.append("Acceso seguro a HubSpot configurado")
    if artifacts["capabilities"].exists:
        gates.append("Primera lectura del portal guardada")
    if artifacts["audit"].exists:
        gates.append("Revision del CRM actual guardada")
    if artifacts["business_context"].exists:
        gates.append("Contexto de negocio guardado")
    if artifacts["setup_spec"].exists and spec_approved:
        gates.append("Diagnostico humano aprobado")
    if artifacts["reconciliation"].exists and reconciliation_current:
        gates.append("Comparacion contra lo existente lista")
    if artifacts["change_plan"].exists and change_plan_current:
        gates.append("Plan humano de cambios listo")
    if artifacts["manifest"].exists and manifest_approved:
        gates.append("Plan de cambios aprobado")
    if artifacts["dry_run_report"].exists and dry_run_current:
        gates.append("Simulacion documentada")
    if artifacts["apply_log"].exists:
        gates.append("Cambios aplicados registrados")
    if artifacts["readback_report"].exists and readback_current:
        gates.append("Verificacion final documentada")
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
        "legacy_app_setup": ["Crear acceso seguro local de HubSpot"],
        "preflight": ["Primera lectura segura del portal"],
        "audit": ["Revision del portal y calidad agregada"],
        "discovery": ["Entender el negocio antes de disenar"],
        "spec_review": ["Revision humana del diagnostico"],
        "design": ["Diseno CRM generado desde el diagnostico aprobado"],
        "reconcile": ["Comparacion del diseno con configuracion existente"],
        "plan": ["Plan exacto de cambios con riesgos y salida manual"],
        "plan_review": ["Plan humano vigente para revisar cambios, riesgos y salida manual"],
        "blocked": ["Resolver conflictos humanos antes de validar"],
        "validate": ["Validacion de seguridad y aprobacion del plan"],
        "dry_run": ["Simulacion persistente antes de cualquier aplicacion real"],
        "ready_to_apply": ["Aprobacion humana explicita para aplicar"],
        "verify": ["Verificacion final contra HubSpot y reporte de evidencia"],
        "verified": ["Revisar y conservar evidencia final"],
    }
    gates = list(gates_by_phase.get(phase, []))
    if artifacts["setup_spec_approval"].exists and not spec_approved:
        gates.append("Volver a aprobar el diagnostico porque cambio")
    if artifacts["reconciliation"].exists and not reconciliation_current:
        gates.append("Regenerar la comparacion porque la propuesta o la lectura cambiaron")
    if artifacts["manifest_approval"].exists and not manifest_approved:
        gates.append("Volver a aprobar el plan porque cambio")
    if artifacts["change_plan"].exists and not change_plan_current:
        gates.append("Actualizar el plan humano porque el plan tecnico cambio")
    if artifacts["dry_run_report"].exists and not dry_run_current:
        gates.append("Repetir la simulacion porque el plan cambio")
    if artifacts["readback_report"].exists and not readback_current:
        gates.append("Actualizar la verificacion final porque el plan cambio")
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
        items.append("Acceso seguro a HubSpot: listo")
    else:
        items.append("Acceso seguro a HubSpot: pendiente")
    for name, label in [
        ("capabilities", "Primera lectura del portal"),
        ("audit", "Revision del CRM actual"),
        ("business_context", "Contexto de negocio"),
        ("setup_spec", "Diagnostico humano"),
        ("design", "Propuesta CRM"),
        ("reconciliation", "Comparacion con lo existente"),
        ("manifest", "Plan de cambios"),
        ("change_plan", "Plan humano de cambios"),
        ("manifest_approval", "Aprobacion del plan"),
        ("dry_run_report", "Reporte de simulacion"),
        ("apply_log", "Registro de cambios aplicados"),
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
