from __future__ import annotations

import hashlib
from pathlib import Path

import typer
from pydantic import ValidationError

from crm_agent.apply import (
    apply_manifest,
    dry_run_manifest,
    dry_run_report_current,
    render_dry_run_report,
)
from crm_agent.audit import build_audit
from crm_agent.change_plan import render_change_plan
from crm_agent.design import build_design
from crm_agent.discovery import build_business_context_from_discovery, write_discovery_outputs
from crm_agent.errors import CrmAgentError
from crm_agent.hubspot import HubSpotConnector
from crm_agent.intake import build_business_context
from crm_agent.io import read_json, read_yaml, utc_now_iso, write_json, write_yaml
from crm_agent.models import (
    BusinessContext,
    CrmAudit,
    CrmDesign,
    CrmReconciliation,
    HubSpotManifest,
    ManifestApproval,
    PortalCapabilities,
    SpecApproval,
)
from crm_agent.onboarding import legacy_app_setup_text
from crm_agent.planner import build_manifest
from crm_agent.reconcile import reconcile_design_with_audit
from crm_agent.research import build_research_registry
from crm_agent.session import (
    append_approval_event,
    append_progress,
    build_session_state,
    format_session_summary,
    persist_session_state,
)
from crm_agent.settings import Settings
from crm_agent.validation import validate_manifest
from crm_agent.verify import verify_manifest

app = typer.Typer(
    no_args_is_help=True, help="Supervised HubSpot CRM/Sales parameterization toolkit."
)


def _fail(error: Exception) -> None:
    typer.secho(str(error), fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1) from error


def _prompt_list(label: str, *, default: str = "") -> list[str]:
    value = typer.prompt(label, default=default).strip()
    if not value:
        return []
    return [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_spec_approval_current(spec: Path, approval_file: Path) -> None:
    if not spec.exists():
        raise ValueError(f"Spec not found: {spec}")
    if not approval_file.exists():
        raise ValueError(
            f"Spec approval not found: {approval_file}. Run approve-spec before design."
        )
    approval = SpecApproval.model_validate(read_json(approval_file))
    if approval.spec_hash != _file_sha256(spec):
        raise ValueError("Spec approval hash does not match current spec. Re-run approve-spec.")


def _assert_change_plan_current(change_plan: Path, manifest: HubSpotManifest) -> None:
    if not change_plan.exists():
        raise ValueError(
            f"Human change plan not found: {change_plan}. Run review-plan before approval."
        )
    text = change_plan.read_text(encoding="utf-8")
    if f"Manifest hash: `{manifest.manifest_hash}`" not in text:
        raise ValueError("Human change plan is stale. Re-run review-plan before approval.")


@app.command("research-registry")
def research_registry(
    out: Path = typer.Option(Path("docs/research_registry.yaml"), help="Output YAML."),
):
    """Write the official source registry used by this toolkit."""
    write_yaml(out, build_research_registry())
    typer.echo(f"Wrote {out}")


@app.command("setup-legacy-app")
def setup_legacy_app():
    """Print the required HubSpot legacy private app setup steps."""
    typer.echo(legacy_app_setup_text())


@app.command()
def start(
    technical: bool = typer.Option(
        False, "--technical", help="Show artifact hashes and technical details."
    ),
):
    """Start the guided HubSpot CRM setup experience."""
    try:
        state = build_session_state()
        persist_session_state(state)
        typer.echo("Bienvenido. Voy a guiarte paso a paso y mantener todo seguro.")
        typer.echo("")
        typer.echo(format_session_summary(state, technical=technical))
    except (CrmAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@app.command("status")
def status_command(
    technical: bool = typer.Option(
        False, "--technical", help="Show artifact hashes and technical details."
    ),
):
    """Resume the current CRM setup state in user-friendly language."""
    try:
        state = build_session_state()
        persist_session_state(state)
        typer.echo(format_session_summary(state, technical=technical))
    except (CrmAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@app.command()
def preflight(out: Path = typer.Option(Path("portal_capabilities.json"), help="Output JSON.")):
    """Read HubSpot portal capabilities without mutating anything."""
    try:
        settings = Settings.from_env(require_token=True)
        connector = HubSpotConnector(settings)
        try:
            capabilities = connector.preflight()
        finally:
            connector.close()
        write_json(out, capabilities)
        typer.echo(f"Wrote {out}")
        if capabilities.warnings:
            typer.secho("Preflight completed with warnings.", fg=typer.colors.YELLOW)
    except (CrmAgentError, ValidationError) as error:
        _fail(error)


@app.command()
def intake(
    project_slug: str = typer.Option(..., help="Namespace for custom properties."),
    business_name: str = typer.Option(..., help="Business name."),
    industry: str | None = typer.Option(None, help="Optional industry."),
    sales_motion: str | None = typer.Option(None, help="Optional sales motion."),
    input_file: list[Path] = typer.Option(None, "--input", "-i", help="Optional notes/docs."),
    out: Path = typer.Option(Path("business_context.yaml"), help="Output YAML."),
):
    """Create an editable business context from interview inputs and optional files."""
    try:
        context = build_business_context(
            project_slug=project_slug,
            business_name=business_name,
            industry=industry,
            sales_motion=sales_motion,
            inputs=input_file or [],
        )
        write_yaml(out, context)
        typer.echo(f"Wrote {out}. Edit it before running design.")
    except (CrmAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@app.command()
def audit(
    capabilities: Path = typer.Option(
        Path("portal_capabilities.json"), help="Portal capabilities JSON."
    ),
    out: Path = typer.Option(Path("crm_audit.yaml"), help="Output YAML."),
    hubs: str = typer.Option("auto", help="Comma-separated hubs or auto."),
    depth: str = typer.Option("metadata-quality", help="metadata or metadata-quality."),
    sample_limit: int = typer.Option(25, min=1, max=100, help="Bounded sample size."),
    live: bool = typer.Option(True, "--live/--no-live", help="Use token for read-only enrichment."),
):
    """Audit existing HubSpot configuration and aggregate data-quality signals."""
    try:
        portal_capabilities = PortalCapabilities.model_validate(read_json(capabilities))
        settings = Settings.from_env(require_token=False)
        connector = None
        if live and settings.hubspot_private_app_token:
            connector = HubSpotConnector(settings)
        elif live:
            typer.secho(
                "No HUBSPOT_PRIVATE_APP_TOKEN found; writing capabilities-only audit.",
                fg=typer.colors.YELLOW,
            )
        try:
            crm_audit = build_audit(
                portal_capabilities,
                connector=connector,
                hubs=hubs,
                depth=depth,
                sample_limit=sample_limit,
            )
        finally:
            if connector is not None:
                connector.close()
        write_yaml(out, crm_audit)
        typer.echo(f"Wrote {out}")
        if crm_audit.warnings:
            typer.secho("Audit completed with warnings.", fg=typer.colors.YELLOW)
    except (CrmAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@app.command()
def discover(
    project_slug: str | None = typer.Option(None, help="Namespace for custom properties."),
    business_name: str | None = typer.Option(None, help="Business name."),
    industry: str | None = typer.Option(None, help="Industry."),
    sales_motion: str | None = typer.Option(None, help="Sales motion."),
    user_role: list[str] | None = typer.Option(
        None,
        "--user-role",
        help="CRM user role/persona. Free text, comma-separated, or repeated.",
    ),
    sales_process_notes: str | None = typer.Option(None, help="Sales process summary."),
    pipeline_stage: list[str] | None = typer.Option(
        None,
        "--pipeline-stage",
        help="Deal pipeline stage. Free text, comma-separated, or repeated.",
    ),
    critical_data: list[str] | None = typer.Option(
        None,
        "--critical-data",
        help=(
            "Critical data. Free text or object:field:label:field_type:option|option. "
            "Can be repeated."
        ),
    ),
    reporting_goal: list[str] | None = typer.Option(
        None, "--reporting-goal", help="Reporting goal. Can be repeated."
    ),
    desired_hubs: str | None = typer.Option(None, help="Desired HubSpot hubs."),
    constraint: list[str] | None = typer.Option(
        None, "--constraint", help="Constraint or business rule. Can be repeated."
    ),
    audit_file: Path = typer.Option(Path("crm_audit.yaml"), "--audit", help="CRM audit YAML."),
    out: Path = typer.Option(Path("business_context.yaml"), help="Business context YAML."),
    spec_out: Path = typer.Option(Path("crm_setup_spec.md"), help="Human-readable spec."),
    interactive: bool = typer.Option(
        True, "--interactive/--no-interactive", help="Prompt for missing answers."
    ),
):
    """Run a guided business discovery and write the setup spec."""
    try:
        if interactive:
            business_name = business_name or typer.prompt("Nombre del negocio")
            project_slug = project_slug or typer.prompt(
                "Namespace corto para propiedades custom", default=business_name
            )
            industry = industry or typer.prompt("Industria", default="")
            sales_motion = sales_motion or typer.prompt("Modelo comercial", default="")
            if not user_role:
                user_role = _prompt_list(
                    "Quienes usaran el CRM y que rol tienen",
                    default="Ventas, Lider comercial",
                )
            sales_process_notes = sales_process_notes or typer.prompt(
                "Describe el proceso comercial desde lead hasta cierre"
            )
            if not pipeline_stage:
                pipeline_stage = _prompt_list(
                    "Etapas reales del pipeline",
                    default="Nuevo, Calificado, Propuesta, Negociacion, Closed Won, Closed Lost",
                )
            if not critical_data:
                critical_data = _prompt_list(
                    "Datos criticos para calificar o reportar",
                    default="Segmento, Fuente, Motivo de perdida",
                )
            if not reporting_goal:
                reporting_goal = _prompt_list(
                    "Vistas o reportes semanales que necesita el equipo",
                    default="Pipeline por etapa, Oportunidades por owner",
                )
            desired_hubs = desired_hubs or typer.prompt(
                "Hubs deseados para este alcance", default="CRM/Sales"
            )
            if not constraint:
                constraint = _prompt_list(
                    "Restricciones o reglas de negocio",
                    default="No escribir sin aprobacion humana",
                )
        missing = [
            name
            for name, value in {
                "business_name": business_name,
                "project_slug": project_slug,
                "sales_process_notes": sales_process_notes,
                "user_role": user_role,
                "pipeline_stage": pipeline_stage,
                "critical_data": critical_data,
                "reporting_goal": reporting_goal,
            }.items()
            if not value
        ]
        if missing:
            raise ValueError(
                "Missing required discovery inputs in --no-interactive mode: " + ", ".join(missing)
            )
        audit = CrmAudit.model_validate(read_yaml(audit_file)) if audit_file.exists() else None
        state = build_session_state()
        context = build_business_context_from_discovery(
            project_slug=project_slug or "",
            business_name=business_name or "",
            industry=industry or None,
            sales_motion=sales_motion or None,
            users=user_role or [],
            sales_process_notes=sales_process_notes or "",
            pipeline_stages=pipeline_stage or [],
            critical_data=critical_data or [],
            reporting_goals=reporting_goal or [],
            desired_hubs=desired_hubs,
            constraints=constraint or [],
        )
        write_discovery_outputs(
            context=context,
            audit=audit,
            state=state,
            context_path=out,
            spec_path=spec_out,
        )
        updated_state = build_session_state()
        persist_session_state(updated_state)
        typer.echo(f"Discovery guardado en {out}")
        typer.echo(f"Diagnostico humano guardado en {spec_out}")
        typer.echo("")
        typer.echo(format_session_summary(updated_state))
    except (CrmAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@app.command("approve-spec")
def approve_spec(
    spec: Path = typer.Option(Path("crm_setup_spec.md"), help="Spec markdown to approve."),
    approved_by: str = typer.Option("local_user", help="Approval identity."),
    out: Path = typer.Option(Path("crm_setup_spec.approval.json"), help="Approval JSON."),
):
    """Approve the human CRM setup spec before design generation."""
    try:
        if not spec.exists():
            raise ValueError(f"Spec not found: {spec}")
        approval = SpecApproval(
            spec_hash=_file_sha256(spec),
            approved_at=utc_now_iso(),
            approved_by=approved_by,
        )
        write_json(out, approval)
        append_approval_event(
            kind="setup_spec",
            artifact_path=spec,
            artifact_hash=approval.spec_hash,
            approved_by=approved_by,
        )
        state = build_session_state()
        persist_session_state(state)
        typer.echo(f"Spec aprobado: {approval.spec_hash}")
        typer.echo(f"Wrote {out}")
    except (CrmAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@app.command()
def design(
    context: Path = typer.Option(Path("business_context.yaml"), help="Business context YAML."),
    capabilities: Path = typer.Option(
        Path("portal_capabilities.json"), help="Portal capabilities JSON."
    ),
    spec: Path = typer.Option(Path("crm_setup_spec.md"), help="Approved setup spec markdown."),
    spec_approval: Path = typer.Option(
        Path("crm_setup_spec.approval.json"), help="Spec approval JSON."
    ),
    out: Path = typer.Option(Path("crm_design.yaml"), help="Output YAML."),
):
    """Map business context to a CRM/Sales core design without writing HubSpot."""
    try:
        _assert_spec_approval_current(spec, spec_approval)
        business_context = BusinessContext.model_validate(read_yaml(context))
        portal_capabilities = PortalCapabilities.model_validate(read_json(capabilities))
        crm_design = build_design(business_context, portal_capabilities)
        write_yaml(out, crm_design)
        typer.echo(f"Wrote {out}")
    except (CrmAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@app.command()
def reconcile(
    design_file: Path = typer.Option(Path("crm_design.yaml"), "--design", help="CRM design YAML."),
    audit_file: Path = typer.Option(Path("crm_audit.yaml"), "--audit", help="CRM audit YAML."),
    out: Path = typer.Option(Path("crm_reconciliation.yaml"), help="Output YAML."),
):
    """Reconcile a desired design with the audited existing portal configuration."""
    try:
        crm_design = CrmDesign.model_validate(read_yaml(design_file))
        crm_audit = CrmAudit.model_validate(read_yaml(audit_file))
        reconciliation = reconcile_design_with_audit(crm_design, crm_audit)
        write_yaml(out, reconciliation)
        typer.echo(f"Wrote {out}")
        if reconciliation.warnings:
            typer.secho("Reconciliation requires review.", fg=typer.colors.YELLOW)
    except (CrmAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@app.command()
def plan(
    design_file: Path = typer.Option(Path("crm_design.yaml"), "--design", help="CRM design YAML."),
    capabilities: Path = typer.Option(
        Path("portal_capabilities.json"), help="Portal capabilities JSON."
    ),
    reconciliation_file: Path = typer.Option(
        Path("crm_reconciliation.yaml"), "--reconciliation", help="CRM reconciliation YAML."
    ),
    out: Path = typer.Option(Path("hubspot_manifest.yaml"), help="Output YAML."),
):
    """Generate an idempotent HubSpot manifest from design, portal facts, and reconciliation."""
    try:
        crm_design = CrmDesign.model_validate(read_yaml(design_file))
        portal_capabilities = PortalCapabilities.model_validate(read_json(capabilities))
        if not reconciliation_file.exists():
            raise ValueError(
                f"Reconciliation not found: {reconciliation_file}. Run reconcile before plan."
            )
        reconciliation = CrmReconciliation.model_validate(read_yaml(reconciliation_file))
        manifest = build_manifest(crm_design, portal_capabilities, reconciliation)
        write_yaml(out, manifest)
        typer.echo(f"Wrote {out}")
        if manifest.has_blockers:
            typer.secho("Manifest has blockers. Run validate for details.", fg=typer.colors.YELLOW)
    except (CrmAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@app.command("review-plan")
def review_plan(
    manifest_file: Path = typer.Option(
        Path("hubspot_manifest.yaml"), "--manifest", help="Manifest YAML."
    ),
    capabilities: Path = typer.Option(
        Path("portal_capabilities.json"), help="Portal capabilities JSON."
    ),
    approval_file: Path = typer.Option(
        Path("hubspot_manifest.approval.json"), "--approval", help="Optional approval JSON."
    ),
    out: Path = typer.Option(Path("crm_change_plan.md"), help="Human-readable change plan."),
):
    """Render a human-readable, supervised change plan from the manifest."""
    try:
        manifest = HubSpotManifest.model_validate(read_yaml(manifest_file))
        portal_capabilities = PortalCapabilities.model_validate(read_json(capabilities))
        approval = (
            ManifestApproval.model_validate(read_json(approval_file))
            if approval_file.exists()
            else None
        )
        plan_text = render_change_plan(
            manifest=manifest,
            capabilities=portal_capabilities,
            approval=approval,
            manifest_path=manifest_file,
            capabilities_path=capabilities,
            approval_path=approval_file,
        )
        out.write_text(plan_text, encoding="utf-8")
        state = build_session_state()
        persist_session_state(state)
        typer.echo(f"Plan humano guardado en {out}")
        typer.echo("")
        typer.echo(format_session_summary(state))
    except (CrmAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@app.command()
def validate(
    manifest_file: Path = typer.Option(
        Path("hubspot_manifest.yaml"), "--manifest", help="Manifest YAML."
    ),
    capabilities: Path = typer.Option(
        Path("portal_capabilities.json"), help="Portal capabilities JSON."
    ),
    approve: bool = typer.Option(False, help="Write approval file when validation passes."),
    approved_by: str = typer.Option("local_user", help="Approval identity."),
    approval_out: Path = typer.Option(
        Path("hubspot_manifest.approval.json"), help="Approval JSON output."
    ),
    report_out: Path | None = typer.Option(None, help="Optional validation report JSON."),
    change_plan: Path = typer.Option(
        Path("crm_change_plan.md"), help="Human-readable change plan markdown."
    ),
):
    """Validate manifest safety rules and optionally approve the current hash."""
    try:
        manifest = HubSpotManifest.model_validate(read_yaml(manifest_file))
        portal_capabilities = PortalCapabilities.model_validate(read_json(capabilities))
        report = validate_manifest(
            manifest,
            portal_capabilities,
            approve=approve,
            approved_by=approved_by,
        )
        if approve and report.passed:
            _assert_change_plan_current(change_plan, manifest)
        if report_out:
            write_json(report_out, report)
        if report.approval:
            write_json(approval_out, report.approval)
            append_approval_event(
                kind="manifest",
                artifact_path=manifest_file,
                artifact_hash=report.approval.manifest_hash,
                approved_by=approved_by,
            )
            typer.echo(f"Approved manifest hash {report.manifest_hash}")
            typer.echo(f"Wrote {approval_out}")
        if report.errors:
            for error in report.errors:
                typer.secho(f"ERROR: {error}", fg=typer.colors.RED)
            raise typer.Exit(code=1)
        for warning in report.warnings:
            typer.secho(f"WARNING: {warning}", fg=typer.colors.YELLOW)
        typer.secho("Manifest validation passed.", fg=typer.colors.GREEN)
    except (CrmAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@app.command()
def apply(
    manifest_file: Path = typer.Option(
        Path("hubspot_manifest.yaml"), "--manifest", help="Manifest YAML."
    ),
    approval_file: Path = typer.Option(
        Path("hubspot_manifest.approval.json"), "--approval", help="Approval JSON."
    ),
    log: Path = typer.Option(Path("apply_log.jsonl"), help="Apply log JSONL."),
    dry_run_report: Path = typer.Option(
        Path("dry_run_report.md"), help="Dry-run report markdown."
    ),
    execute: bool = typer.Option(False, help="Actually write to HubSpot. Default is dry-run."),
):
    """Apply an approved manifest. Defaults to dry-run."""
    try:
        manifest = HubSpotManifest.model_validate(read_yaml(manifest_file))
        approval = ManifestApproval.model_validate(read_json(approval_file))
        if not execute:
            typer.secho("Dry-run only. Add --execute to write to HubSpot.", fg=typer.colors.YELLOW)
            connector = None
            results = dry_run_manifest(manifest=manifest, approval=approval)
            dry_run_report.write_text(
                render_dry_run_report(
                    manifest=manifest,
                    approval=approval,
                    results=results,
                    manifest_path=manifest_file,
                    approval_path=approval_file,
                ),
                encoding="utf-8",
            )
            append_progress(
                f"{utc_now_iso()} dry-run completed for {manifest_file}; "
                f"report written to {dry_run_report}"
            )
            typer.echo(f"Wrote {dry_run_report}")
        else:
            if not dry_run_report_current(dry_run_report, manifest):
                raise ValueError(
                    "Dry-run report is missing or stale. Run apply without --execute first."
                )
            settings = Settings.from_env(require_token=True)
            connector = HubSpotConnector(settings)
            try:
                results = apply_manifest(
                    manifest=manifest,
                    approval=approval,
                    connector=connector,
                    log_path=log,
                    execute=execute,
                )
            finally:
                connector.close()
            append_progress(f"{utc_now_iso()} execute apply completed for {manifest_file}")
        state = build_session_state()
        persist_session_state(state)
        for result in results:
            typer.echo(result)
    except (CrmAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@app.command()
def verify(
    manifest_file: Path = typer.Option(
        Path("hubspot_manifest.yaml"), "--manifest", help="Manifest YAML."
    ),
    out: Path = typer.Option(Path("readback_report.md"), help="Output markdown."),
):
    """Read HubSpot back and compare against manifest expectations."""
    try:
        manifest = HubSpotManifest.model_validate(read_yaml(manifest_file))
        settings = Settings.from_env(require_token=True)
        connector = HubSpotConnector(settings)
        try:
            report = verify_manifest(manifest, connector)
        finally:
            connector.close()
        out.write_text(report, encoding="utf-8")
        append_progress(f"{utc_now_iso()} readback verified for {manifest_file}; report {out}")
        state = build_session_state()
        persist_session_state(state)
        typer.echo(f"Wrote {out}")
    except (CrmAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


if __name__ == "__main__":
    app()
