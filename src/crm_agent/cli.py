from __future__ import annotations

from pathlib import Path

import typer
from pydantic import ValidationError

from crm_agent.apply import apply_manifest
from crm_agent.design import build_design
from crm_agent.errors import CrmAgentError
from crm_agent.hubspot import HubSpotConnector
from crm_agent.intake import build_business_context
from crm_agent.io import read_json, read_yaml, write_json, write_yaml
from crm_agent.models import (
    BusinessContext,
    CrmDesign,
    HubSpotManifest,
    ManifestApproval,
    PortalCapabilities,
)
from crm_agent.onboarding import legacy_app_setup_text
from crm_agent.planner import build_manifest
from crm_agent.research import build_research_registry
from crm_agent.settings import Settings
from crm_agent.validation import validate_manifest
from crm_agent.verify import verify_manifest

app = typer.Typer(
    no_args_is_help=True, help="Supervised HubSpot CRM/Sales parameterization toolkit."
)


def _fail(error: Exception) -> None:
    typer.secho(str(error), fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1) from error


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
def design(
    context: Path = typer.Option(Path("business_context.yaml"), help="Business context YAML."),
    capabilities: Path = typer.Option(
        Path("portal_capabilities.json"), help="Portal capabilities JSON."
    ),
    out: Path = typer.Option(Path("crm_design.yaml"), help="Output YAML."),
):
    """Map business context to a CRM/Sales core design without writing HubSpot."""
    try:
        business_context = BusinessContext.model_validate(read_yaml(context))
        portal_capabilities = PortalCapabilities.model_validate(read_json(capabilities))
        crm_design = build_design(business_context, portal_capabilities)
        write_yaml(out, crm_design)
        typer.echo(f"Wrote {out}")
    except (CrmAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@app.command()
def plan(
    design_file: Path = typer.Option(Path("crm_design.yaml"), "--design", help="CRM design YAML."),
    capabilities: Path = typer.Option(
        Path("portal_capabilities.json"), help="Portal capabilities JSON."
    ),
    out: Path = typer.Option(Path("hubspot_manifest.yaml"), help="Output YAML."),
):
    """Generate an idempotent HubSpot manifest from design and current portal facts."""
    try:
        crm_design = CrmDesign.model_validate(read_yaml(design_file))
        portal_capabilities = PortalCapabilities.model_validate(read_json(capabilities))
        manifest = build_manifest(crm_design, portal_capabilities)
        write_yaml(out, manifest)
        typer.echo(f"Wrote {out}")
        if manifest.has_blockers:
            typer.secho("Manifest has blockers. Run validate for details.", fg=typer.colors.YELLOW)
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
        if report_out:
            write_json(report_out, report)
        if report.approval:
            write_json(approval_out, report.approval)
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
    execute: bool = typer.Option(False, help="Actually write to HubSpot. Default is dry-run."),
):
    """Apply an approved manifest. Defaults to dry-run."""
    try:
        manifest = HubSpotManifest.model_validate(read_yaml(manifest_file))
        approval = ManifestApproval.model_validate(read_json(approval_file))
        settings = Settings.from_env(require_token=execute)
        if not execute:
            typer.secho("Dry-run only. Add --execute to write to HubSpot.", fg=typer.colors.YELLOW)
            connector = None
        else:
            connector = HubSpotConnector(settings)
        try:
            if connector is None:
                from crm_agent.apply import assert_approval

                assert_approval(manifest, approval)
                results = [
                    {
                        "operation_id": operation.id,
                        "action": operation.action,
                        "status": "dry_run" if operation.status == "planned" else "skipped",
                    }
                    for operation in manifest.operations
                ]
            else:
                results = apply_manifest(
                    manifest=manifest,
                    approval=approval,
                    connector=connector,
                    log_path=log,
                    execute=execute,
                )
        finally:
            if connector is not None:
                connector.close()
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
        typer.echo(f"Wrote {out}")
    except (CrmAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


if __name__ == "__main__":
    app()
