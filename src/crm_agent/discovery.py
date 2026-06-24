from __future__ import annotations

from pathlib import Path

from crm_agent.io import slugify, utc_now_iso, write_yaml
from crm_agent.models import BusinessContext, CrmAudit, SessionState
from crm_agent.session import DISCOVERY_LEDGER_FILE, append_progress


def build_business_context_from_discovery(
    *,
    project_slug: str,
    business_name: str,
    industry: str | None = None,
    sales_motion: str | None = None,
    users: list[str] | None = None,
    sales_process_notes: str,
    pipeline_stages: list[str] | None = None,
    critical_data: list[str] | None = None,
    reporting_goals: list[str] | None = None,
    desired_hubs: str | None = None,
    constraints: list[str] | None = None,
) -> BusinessContext:
    data_requirements = [_parse_critical_data(item) for item in _normalize_items(critical_data)]
    notes = []
    if desired_hubs:
        notes.append(f"Hubs deseados: {desired_hubs}")
    for constraint in _normalize_items(constraints):
        notes.append(f"Restriccion: {constraint}")
    return BusinessContext(
        project_slug=slugify(project_slug),
        business_name=business_name,
        industry=industry,
        sales_motion=sales_motion,
        users=_normalize_items(users),
        sales_process_notes=sales_process_notes,
        pipeline_stages=_normalize_items(pipeline_stages),
        data_requirements=[item for item in data_requirements if item],
        reporting_goals=_normalize_items(reporting_goals),
        raw_notes="\n".join(notes),
    )


def write_discovery_outputs(
    *,
    context: BusinessContext,
    audit: CrmAudit | None,
    state: SessionState,
    context_path: Path,
    spec_path: Path,
    root: Path = Path("."),
) -> None:
    write_yaml(context_path, context)
    spec = render_setup_spec(context=context, audit=audit, state=state)
    spec_path.write_text(spec, encoding="utf-8")
    _append_discovery_ledger(context, spec_path, root=root)
    append_progress(
        (
            f"{utc_now_iso()} discovery captured for {context.business_name}; "
            f"spec written to {spec_path}"
        ),
        root=root,
    )


def render_setup_spec(
    *, context: BusinessContext, audit: CrmAudit | None, state: SessionState
) -> str:
    lines = [
        "# Diagnostico y ruta recomendada de HubSpot CRM",
        "",
        "## Resumen",
        f"- Empresa: {context.business_name}",
        f"- Namespace propuesto: `{context.project_slug}`",
        f"- Industria: {context.industry or 'pendiente'}",
        f"- Movimiento comercial: {context.sales_motion or 'pendiente'}",
        (
            "- Usuarios/roles: "
            f"{', '.join(context.users) if context.users else 'pendiente'}"
        ),
        "- Estado: este documento es read-only y debe aprobarse antes de generar diseno.",
        "",
        "## Proceso comercial entendido",
        context.sales_process_notes or "Pendiente de completar.",
        "",
        "## Etapas del pipeline",
        (
            "- Etapas propuestas: "
            f"{', '.join(context.pipeline_stages) if context.pipeline_stages else 'pendiente'}"
        ),
        "",
        "## Datos y reporting",
        f"- Datos criticos identificados: {len(context.data_requirements)}",
        (
            "- Reportes esperados: "
            f"{', '.join(context.reporting_goals) if context.reporting_goals else 'pendiente'}"
        ),
        "",
        "## Diagnostico del portal",
    ]
    if audit:
        available = [
            hub for hub, result in audit.hubs.items() if result.availability.status == "available"
        ]
        partial = [
            hub for hub, result in audit.hubs.items() if result.availability.status == "partial"
        ]
        unavailable = [
            hub
            for hub, result in audit.hubs.items()
            if result.availability.status == "not_available"
        ]
        lines.extend(
            [
                f"- Audit live: {'si' if audit.live_enrichment else 'no'}",
                (
                    "- Hubs disponibles: "
                    f"{', '.join(available) if available else 'ninguno confirmado'}"
                ),
                f"- Hubs parciales: {', '.join(partial) if partial else 'ninguno'}",
                f"- Hubs no disponibles: {', '.join(unavailable) if unavailable else 'ninguno'}",
                f"- Findings agregados: {len(audit.findings)}",
            ]
        )
    else:
        lines.append("- No encontre crm_audit.yaml; primero conviene correr audit read-only.")
    lines.extend(
        [
            "",
            "## Ruta recomendada",
            "- Mantener todo en modo read-only hasta completar diseno, reconciliacion y manifest.",
            (
                "- Reutilizar propiedades o pipelines existentes solo cuando reconcile "
                "tenga alta confianza."
            ),
            "- Bloquear conflictos o coincidencias ambiguas para decision humana.",
            "- Aprobar este diagnostico por hash antes de generar diseno tecnico.",
            "",
            "## Preguntas abiertas",
        ]
    )
    open_questions = _open_questions(context=context, audit=audit, state=state)
    if open_questions:
        lines.extend(f"- {question}" for question in open_questions)
    else:
        lines.append("- No hay preguntas criticas pendientes para pasar a diseno supervisado.")
    lines.extend(
        [
            "",
            "## Gates antes de escribir",
            "- `crm_setup_spec.md` aprobado por hash vigente.",
            "- `crm_design.yaml` generado desde el contexto aprobado.",
            "- `crm_reconciliation.yaml` comparado contra audit actual.",
            "- `hubspot_manifest.yaml` validado sin blockers.",
            "- `hubspot_manifest.approval.json` vigente para el hash actual.",
            "- Dry-run de `crm-agent apply` revisado antes de cualquier `--execute`.",
            "",
            "## Fuera de alcance V1",
            (
                "- Workflows, dashboards, reportes, formularios, permisos, merges, "
                "deletes y renombres automaticos."
            ),
            "",
            "## Bloqueos actuales",
        ]
    )
    if state.blockers:
        lines.extend(f"- {blocker}" for blocker in state.blockers)
    else:
        lines.append("- Ningun bloqueo detectado por ahora.")
    lines.extend(
        [
            "",
            "## Aprobacion",
            "Si este diagnostico es correcto, apruebalo con:",
            "",
            "```bash",
            "crm-agent approve-spec --spec crm_setup_spec.md",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def _open_questions(
    *, context: BusinessContext, audit: CrmAudit | None, state: SessionState
) -> list[str]:
    questions: list[str] = []
    if not context.users:
        questions.append("Quienes usaran el CRM y que necesita ver o actualizar cada rol?")
    if not context.data_requirements:
        questions.append("Que datos son obligatorios para calificar cuentas, contactos o deals?")
    if not context.reporting_goals:
        questions.append("Que vistas o reportes deben revisar los lideres semanalmente?")
    if not context.pipeline_stages:
        questions.append("Que etapas reales debe tener el pipeline comercial?")
    if audit is None:
        questions.append(
            "Falta audit read-only; no se ha probado que configuracion existente conviene "
            "conservar."
        )
    elif any(item.availability.status == "available" for item in audit.hubs.values()):
        questions.append(
            "Que assets existentes son intocables aunque el diseno proponga algo parecido?"
        )
    if state.blockers:
        questions.append(
            "Hay blockers actuales en el estado; deben resolverse antes de planear cambios."
        )
    return questions


def discovery_questions(audit: CrmAudit | None) -> list[str]:
    questions = [
        "Cual es el nombre del negocio?",
        "Como describirias el proceso comercial desde lead hasta cierre?",
        "Que datos son obligatorios para calificar una oportunidad?",
        "Que reportes o vistas necesita revisar el equipo cada semana?",
    ]
    if audit and any(item.availability.status == "available" for item in audit.hubs.values()):
        questions.append(
            "Hay configuracion existente en HubSpot. "
            "Que elementos quieres conservar si son compatibles?"
        )
    if audit and any(item.availability.status == "not_available" for item in audit.hubs.values()):
        questions.append(
            "Algunos hubs no estan disponibles por scopes o plan. Cuales son realmente necesarios?"
        )
    return questions


def _append_discovery_ledger(context: BusinessContext, spec_path: Path, *, root: Path) -> None:
    ledger = root / DISCOVERY_LEDGER_FILE
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(f"## {utc_now_iso()} - {context.business_name}\n\n")
        handle.write(f"- Namespace: `{context.project_slug}`\n")
        if context.industry:
            handle.write(f"- Industria: {context.industry}\n")
        if context.sales_motion:
            handle.write(f"- Movimiento comercial: {context.sales_motion}\n")
        if context.users:
            handle.write(f"- Usuarios/roles: {', '.join(context.users)}\n")
        if context.pipeline_stages:
            handle.write(f"- Etapas pipeline: {', '.join(context.pipeline_stages)}\n")
        handle.write(f"- Spec: {spec_path}\n\n")


def _normalize_items(items: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for item in items or []:
        for part in item.replace(";", ",").split(","):
            value = part.strip()
            if value:
                normalized.append(value)
    return normalized


def _parse_critical_data(raw: str) -> dict | None:
    parts = [part.strip() for part in raw.split(":")]
    if len(parts) < 3:
        return {
            "object_type": "companies",
            "field_name": slugify(raw),
            "label": raw.strip().title(),
            "type": "string",
            "field_type": "text",
            "reason": "Dato critico capturado durante discovery.",
        }
    object_type, field_name, label = parts[:3]
    field_type = parts[3] if len(parts) >= 4 and parts[3] else "text"
    options = parts[4].split("|") if len(parts) >= 5 and parts[4] else []
    return {
        "object_type": object_type,
        "field_name": field_name,
        "label": label,
        "type": "enumeration" if options else "string",
        "field_type": "select" if options else field_type,
        "options": options,
        "reason": "Dato critico capturado durante discovery.",
    }
