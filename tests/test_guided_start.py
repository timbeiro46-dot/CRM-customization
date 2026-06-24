from __future__ import annotations

import hashlib
from pathlib import Path

from typer.testing import CliRunner

from crm_agent.cli import app
from crm_agent.io import read_yaml, stable_hash, write_json, write_yaml
from crm_agent.models import (
    AuditObjectMetadata,
    BusinessContext,
    CrmAudit,
    CrmDesign,
    CrmReconciliation,
    HubSpotManifest,
    ManifestApproval,
    ManifestOperation,
    PipelineSpec,
    PipelineStageSpec,
    PortalCapabilities,
    PortalObjectCapabilities,
    SpecApproval,
)
from crm_agent.session import build_session_state, format_session_summary


def fake_capabilities() -> PortalCapabilities:
    return PortalCapabilities(
        generated_at="2026-06-23T00:00:00+00:00",
        api_version="2026-03",
        objects={
            "companies": PortalObjectCapabilities(object_type="companies", readable=True),
            "contacts": PortalObjectCapabilities(object_type="contacts", readable=True),
            "deals": PortalObjectCapabilities(object_type="deals", readable=True),
        },
    )


def fake_audit(capabilities: PortalCapabilities) -> CrmAudit:
    return CrmAudit(
        generated_at="2026-06-23T00:00:00+00:00",
        api_version="2026-03",
        capability_hash=stable_hash(capabilities),
        live_enrichment=False,
        hubs={},
        objects={},
    )


def fake_audit_with_existing_configuration(capabilities: PortalCapabilities) -> CrmAudit:
    return CrmAudit(
        generated_at="2026-06-23T00:00:00+00:00",
        api_version="2026-03",
        capability_hash=stable_hash(capabilities),
        live_enrichment=True,
        hubs={},
        objects={
            "companies": AuditObjectMetadata(
                object_type="companies",
                property_count=42,
            )
        },
    )


def test_session_router_starts_with_legacy_app_when_token_missing(tmp_path) -> None:
    state = build_session_state(tmp_path)

    assert state.phase == "legacy_app_setup"
    assert state.next_action.command == "crm-agent setup-legacy-app"
    assert not state.safe_to_write


def test_session_router_moves_from_preflight_to_audit(tmp_path) -> None:
    (tmp_path / ".env").write_text("HUBSPOT_PRIVATE_APP_TOKEN=pat-na1-test\n", encoding="utf-8")

    state = build_session_state(tmp_path)
    assert state.phase == "preflight"

    write_json(tmp_path / "portal_capabilities.json", fake_capabilities())
    state = build_session_state(tmp_path)
    assert state.phase == "audit"


def test_discover_cli_writes_context_spec_and_user_friendly_output(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    capabilities = fake_capabilities()
    write_json(tmp_path / "portal_capabilities.json", capabilities)
    audit = fake_audit(capabilities)
    write_yaml(tmp_path / "crm_audit.yaml", audit)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "discover",
            "--no-interactive",
            "--business-name",
            "Acme",
            "--project-slug",
            "acme",
            "--sales-process-notes",
            "Inbound lead, qualification, proposal, negotiation and close.",
            "--user-role",
            "Sales team",
            "--pipeline-stage",
            "Inbound",
            "--pipeline-stage",
            "Qualified",
            "--pipeline-stage",
            "Proposal",
            "--critical-data",
            "companies:segment:Segment:text",
            "--reporting-goal",
            "Pipeline health by owner",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "business_context.yaml").exists()
    assert (tmp_path / "crm_setup_spec.md").exists()
    assert (tmp_path / ".crm-agent" / "discovery_ledger.md").exists()
    spec = (tmp_path / "crm_setup_spec.md").read_text(encoding="utf-8")
    assert "## Preguntas abiertas" in spec
    assert "## Gates seguros antes de escribir" in spec
    assert "Usuarios/roles: Sales team" in spec
    assert "Etapas propuestas: Inbound, Qualified, Proposal" in spec
    assert "Quienes usaran el CRM" not in spec
    assert "Que etapas reales" not in spec
    assert "planner.py" not in result.output
    assert "Siguiente paso seguro" in result.output


def test_status_summary_shows_phase_route_and_one_strategic_question(tmp_path) -> None:
    (tmp_path / ".env").write_text("HUBSPOT_PRIVATE_APP_TOKEN=pat-na1-test\n", encoding="utf-8")
    capabilities = fake_capabilities()
    write_json(tmp_path / "portal_capabilities.json", capabilities)
    write_yaml(tmp_path / "crm_audit.yaml", fake_audit(capabilities))

    state = build_session_state(tmp_path)
    summary = format_session_summary(state)

    assert state.phase == "discovery"
    assert "Agente CRM guiado" in summary
    assert "Ruta:" in summary
    assert "* Descubrir" in summary
    assert "Pregunta estrategica ahora" in summary
    assert "Tienes pagina web, Excel, CSV o documento" in summary
    assert "Como entra, avanza y se cierra" not in summary
    assert "planner.py" not in summary
    assert "No se escribira nada en HubSpot" in summary


def test_setup_spec_adapts_to_existing_portal_without_technical_leak(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    capabilities = fake_capabilities()
    write_json(tmp_path / "portal_capabilities.json", capabilities)
    write_yaml(tmp_path / "crm_audit.yaml", fake_audit_with_existing_configuration(capabilities))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "discover",
            "--no-interactive",
            "--business-name",
            "Acme",
            "--project-slug",
            "acme",
            "--sales-process-notes",
            "Inbound lead, qualification, proposal, negotiation and close.",
            "--user-role",
            "Sales team",
            "--pipeline-stage",
            "Inbound",
            "--critical-data",
            "companies:segment:Segment:text",
            "--reporting-goal",
            "Pipeline health by owner",
        ],
    )

    assert result.exit_code == 0, result.output
    spec = (tmp_path / "crm_setup_spec.md").read_text(encoding="utf-8")
    assert "# Ruta recomendada para adaptar HubSpot CRM" in spec
    assert "El portal ya tiene configuracion visible" in spec
    assert "Siguiente pregunta estrategica" in spec
    assert "crm_change_plan.md" in spec
    assert "Artefactos tecnicos de soporte" in spec
    assert "No necesitas editar estos archivos" in spec


def test_discover_cli_accepts_website_and_process_source_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    capabilities = fake_capabilities()
    write_json(tmp_path / "portal_capabilities.json", capabilities)
    write_yaml(tmp_path / "crm_audit.yaml", fake_audit(capabilities))
    source_file = tmp_path / "proceso_ventas.csv"
    source_file.write_text(
        "etapa,entrada,salida\nLead,Formulario web,Calificado\nPropuesta,Demo enviada,Cierre\n",
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "discover",
            "--no-interactive",
            "--business-name",
            "Acme",
            "--project-slug",
            "acme",
            "--website-url",
            "acme.example",
            "--source-file",
            str(source_file),
            "--sales-process-notes",
            "Inbound lead, qualification, proposal, negotiation and close.",
            "--user-role",
            "Sales team",
            "--pipeline-stage",
            "Inbound",
            "--critical-data",
            "companies:segment:Segment:text",
            "--reporting-goal",
            "Pipeline health by owner",
        ],
    )

    assert result.exit_code == 0, result.output
    context = read_yaml(tmp_path / "business_context.yaml")
    assert "https://acme.example" in context["source_documents"]
    assert str(source_file) in context["source_documents"]
    assert "Fuente web declarada" in context["raw_notes"]
    assert "Vista previa tabular" in context["raw_notes"]
    spec = (tmp_path / "crm_setup_spec.md").read_text(encoding="utf-8")
    assert "## Fuentes aportadas para contexto" in spec
    assert "https://acme.example" in spec
    assert "Tienes pagina web, Excel" not in spec


def test_start_cli_reports_safe_next_step_without_technical_map(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["start"])

    assert result.exit_code == 0, result.output
    assert "Fase 1 - Conexion segura" in result.output
    assert "planner.py" not in result.output
    assert (tmp_path / ".crm-agent" / "session_state.yaml").exists()


def test_spec_approval_must_match_current_spec_hash(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("HUBSPOT_PRIVATE_APP_TOKEN=pat-na1-test\n", encoding="utf-8")
    capabilities = fake_capabilities()
    write_json(tmp_path / "portal_capabilities.json", capabilities)
    audit = fake_audit(capabilities)
    write_yaml(tmp_path / "crm_audit.yaml", audit)
    runner = CliRunner()

    discover_result = runner.invoke(
        app,
        [
            "discover",
            "--no-interactive",
            "--business-name",
            "Acme",
            "--project-slug",
            "acme",
            "--sales-process-notes",
            "Inbound lead, qualification, proposal, negotiation and close.",
            "--user-role",
            "Sales team",
            "--pipeline-stage",
            "Inbound, Qualified, Proposal",
            "--critical-data",
            "companies:segment:Segment:text",
            "--reporting-goal",
            "Pipeline health by owner",
        ],
    )
    assert discover_result.exit_code == 0, discover_result.output

    approval_result = runner.invoke(app, ["approve-spec"])
    assert approval_result.exit_code == 0, approval_result.output
    assert (tmp_path / ".crm-agent" / "approval_ledger.md").exists()
    assert build_session_state(tmp_path).phase == "design"

    with (tmp_path / "crm_setup_spec.md").open("a", encoding="utf-8") as handle:
        handle.write("\nCambio posterior a la aprobacion.\n")

    state = build_session_state(tmp_path)
    assert state.phase == "spec_review"
    assert any("no coincide" in blocker for blocker in state.blockers)


def test_design_cli_requires_current_spec_approval(tmp_path) -> None:
    runner = CliRunner()
    capabilities = fake_capabilities()
    write_json(tmp_path / "portal_capabilities.json", capabilities)
    write_yaml(
        tmp_path / "business_context.yaml",
        BusinessContext(
            project_slug="acme",
            business_name="Acme",
            users=["Sales"],
            sales_process_notes="Lead to close.",
            pipeline_stages=["Inbound", "Qualified"],
            reporting_goals=["Pipeline health"],
        ),
    )
    (tmp_path / "crm_setup_spec.md").write_text("# Spec\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "design",
            "--context",
            str(tmp_path / "business_context.yaml"),
            "--capabilities",
            str(tmp_path / "portal_capabilities.json"),
            "--spec",
            str(tmp_path / "crm_setup_spec.md"),
            "--out",
            str(tmp_path / "crm_design.yaml"),
        ],
    )

    assert result.exit_code != 0
    assert "Run approve-spec before design" in result.output


def test_manifest_approval_must_match_current_manifest_hash(tmp_path) -> None:
    (tmp_path / ".env").write_text("HUBSPOT_PRIVATE_APP_TOKEN=pat-na1-test\n", encoding="utf-8")
    capabilities = fake_capabilities()
    write_json(tmp_path / "portal_capabilities.json", capabilities)
    audit = fake_audit(capabilities)
    write_yaml(tmp_path / "crm_audit.yaml", audit)
    (tmp_path / "business_context.yaml").write_text(
        "project_slug: acme\n"
        "business_name: Acme\n"
        "sales_process_notes: Lead to close.\n"
        "reporting_goals:\n"
        "- Pipeline health\n",
        encoding="utf-8",
    )
    spec_path = tmp_path / "crm_setup_spec.md"
    spec_path.write_text("# Spec\n", encoding="utf-8")
    write_json(
        tmp_path / "crm_setup_spec.approval.json",
        SpecApproval(
            spec_hash=hashlib.sha256(spec_path.read_bytes()).hexdigest(),
            approved_at="2026-06-23T00:00:00+00:00",
        ),
    )
    design = CrmDesign(
        generated_at="2026-06-23T00:00:00+00:00",
        project_slug="acme",
        business_name="Acme",
        properties=[],
        pipelines=[
            PipelineSpec(
                object_type="deals",
                label="Main Sales",
                stages=[PipelineStageSpec(label="New opportunity")],
            )
        ],
    )
    reconciliation = CrmReconciliation(
        generated_at="2026-06-23T00:00:00+00:00",
        design_hash=stable_hash(design),
        audit_hash=audit.audit_hash,
        capability_hash=stable_hash(capabilities),
        decisions=[],
    )
    manifest = HubSpotManifest(
        generated_at="2026-06-23T00:00:00+00:00",
        api_version="2026-03",
        project_slug="acme",
        design_hash="design",
        capability_hash="test",
        reconciliation_hash="reconcile",
        operations=[
            ManifestOperation(
                id="pipeline:deals:Main Sales",
                action="ensure_pipeline",
                object_type="deals",
                method="POST",
                endpoint="/crm/pipelines/2026-03/deals",
                rollback="Archive manually.",
            )
        ],
    )
    write_yaml(tmp_path / "crm_design.yaml", design)
    write_yaml(tmp_path / "crm_reconciliation.yaml", reconciliation)
    write_yaml(tmp_path / "hubspot_manifest.yaml", manifest)
    write_json(
        tmp_path / "hubspot_manifest.approval.json",
        ManifestApproval(
            manifest_hash="wrong",
            approved_at="2026-06-23T00:00:00+00:00",
        ),
    )

    state = build_session_state(tmp_path)
    assert state.phase == "plan_review"

    (tmp_path / "crm_change_plan.md").write_text(
        f"Manifest hash: `{manifest.manifest_hash}`\n", encoding="utf-8"
    )
    state = build_session_state(tmp_path)
    assert state.phase == "validate"
    assert any("hubspot_manifest.yaml" in gate for gate in state.pending_gates)


def test_session_routes_stale_reconciliation_back_to_reconcile(tmp_path) -> None:
    (tmp_path / ".env").write_text("HUBSPOT_PRIVATE_APP_TOKEN=pat-na1-test\n", encoding="utf-8")
    capabilities = fake_capabilities()
    audit = fake_audit(capabilities)
    write_json(tmp_path / "portal_capabilities.json", capabilities)
    write_yaml(tmp_path / "crm_audit.yaml", audit)
    (tmp_path / "business_context.yaml").write_text(
        "project_slug: acme\n"
        "business_name: Acme\n"
        "sales_process_notes: Lead to close.\n"
        "reporting_goals:\n"
        "- Pipeline health\n",
        encoding="utf-8",
    )
    spec_path = tmp_path / "crm_setup_spec.md"
    spec_path.write_text("# Spec\n", encoding="utf-8")
    write_json(
        tmp_path / "crm_setup_spec.approval.json",
        SpecApproval(
            spec_hash=hashlib.sha256(spec_path.read_bytes()).hexdigest(),
            approved_at="2026-06-23T00:00:00+00:00",
        ),
    )
    write_yaml(
        tmp_path / "crm_design.yaml",
        CrmDesign(
            generated_at="2026-06-23T00:00:00+00:00",
            project_slug="acme",
            business_name="Acme",
            properties=[],
            pipelines=[],
        ),
    )
    write_yaml(
        tmp_path / "crm_reconciliation.yaml",
        CrmReconciliation(
            generated_at="2026-06-23T00:00:00+00:00",
            design_hash="stale",
            audit_hash=audit.audit_hash,
            capability_hash=stable_hash(capabilities),
            decisions=[],
        ),
    )

    state = build_session_state(tmp_path)

    assert state.phase == "reconcile"
    assert state.next_action.command is not None
    assert "crm-agent reconcile" in state.next_action.command
    assert any("Regenerar crm_reconciliation.yaml" in gate for gate in state.pending_gates)
    assert not any(
        "Reconciliacion contra lo existente vigente" in gate for gate in state.completed_gates
    )


def test_session_routes_apply_log_to_current_readback_gate(tmp_path) -> None:
    (tmp_path / ".env").write_text("HUBSPOT_PRIVATE_APP_TOKEN=pat-na1-test\n", encoding="utf-8")
    capabilities = fake_capabilities()
    write_json(tmp_path / "portal_capabilities.json", capabilities)
    audit = fake_audit(capabilities)
    write_yaml(tmp_path / "crm_audit.yaml", audit)
    (tmp_path / "business_context.yaml").write_text(
        "project_slug: acme\n"
        "business_name: Acme\n"
        "sales_process_notes: Lead to close.\n"
        "reporting_goals:\n"
        "- Pipeline health\n",
        encoding="utf-8",
    )
    spec_path = tmp_path / "crm_setup_spec.md"
    spec_path.write_text("# Spec\n", encoding="utf-8")
    write_json(
        tmp_path / "crm_setup_spec.approval.json",
        SpecApproval(
            spec_hash=hashlib.sha256(spec_path.read_bytes()).hexdigest(),
            approved_at="2026-06-23T00:00:00+00:00",
        ),
    )
    design = CrmDesign(
        generated_at="2026-06-23T00:00:00+00:00",
        project_slug="acme",
        business_name="Acme",
        properties=[],
        pipelines=[
            PipelineSpec(
                object_type="deals",
                label="Main Sales",
                stages=[PipelineStageSpec(label="New opportunity")],
            )
        ],
    )
    manifest = HubSpotManifest(
        generated_at="2026-06-23T00:00:00+00:00",
        api_version="2026-03",
        project_slug="acme",
        design_hash="design",
        capability_hash="test",
        operations=[
            ManifestOperation(
                id="pipeline:deals:Main Sales",
                action="ensure_pipeline",
                object_type="deals",
                method="POST",
                endpoint="/crm/pipelines/2026-03/deals",
                rollback="Archive manually.",
            )
        ],
    )
    write_yaml(tmp_path / "crm_design.yaml", design)
    write_yaml(
        tmp_path / "crm_reconciliation.yaml",
        CrmReconciliation(
            generated_at="2026-06-23T00:00:00+00:00",
            design_hash=stable_hash(design),
            audit_hash=audit.audit_hash,
            capability_hash=stable_hash(capabilities),
            decisions=[],
        ),
    )
    write_yaml(tmp_path / "hubspot_manifest.yaml", manifest)
    (tmp_path / "crm_change_plan.md").write_text(
        f"Manifest hash: `{manifest.manifest_hash}`\n", encoding="utf-8"
    )
    write_json(
        tmp_path / "hubspot_manifest.approval.json",
        ManifestApproval(
            manifest_hash=manifest.manifest_hash,
            approved_at="2026-06-23T00:00:00+00:00",
        ),
    )
    (tmp_path / "dry_run_report.md").write_text(
        f"Manifest hash: `{manifest.manifest_hash}`\n", encoding="utf-8"
    )
    (tmp_path / "apply_log.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "readback_report.md").write_text(
        "Manifest hash: `old`\n", encoding="utf-8"
    )

    state = build_session_state(tmp_path)
    assert state.phase == "verify"
    assert any("readback_report.md" in gate for gate in state.pending_gates)

    (tmp_path / "readback_report.md").write_text(
        f"Manifest hash: `{manifest.manifest_hash}`\n", encoding="utf-8"
    )
    state = build_session_state(tmp_path)
    assert state.phase == "verified"
    assert any("Readback" in gate for gate in state.completed_gates)


def test_claude_assets_exist_and_enforce_consultant_mode() -> None:
    root = Path(__file__).resolve().parents[1]
    claude = (root / "CLAUDE.md").read_text(encoding="utf-8")
    start_skill = (root / ".claude/skills/crm-start/SKILL.md").read_text(encoding="utf-8")
    discovery_skill = (root / ".claude/skills/crm-discovery/SKILL.md").read_text(encoding="utf-8")
    status_skill = (root / ".claude/skills/crm-status/SKILL.md").read_text(encoding="utf-8")
    guided_doc = (root / "docs/guided_experience.md").read_text(encoding="utf-8")

    assert "CRM consultant" in claude
    assert "Connect" in claude
    assert "Verify" in claude
    assert "Do not run `crm-agent apply --execute`" in start_skill
    assert "one strategic question" in start_skill
    assert "adaptive interview" in discovery_skill
    assert "Ask one high-value question at a time" in discovery_skill
    assert "--source-file" in discovery_skill
    assert "Resume from artifacts" in status_skill
    assert "strategic question" in status_skill
    assert "Ask one question at a time" in guided_doc
    assert "Human-Facing Documents" in guided_doc
