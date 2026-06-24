from __future__ import annotations

from typer.testing import CliRunner

from crm_agent.cli import app
from crm_agent.io import write_json, write_yaml
from crm_agent.models import (
    CrmDesign,
    PipelineSpec,
    PipelineStageSpec,
    PortalCapabilities,
    PortalObjectCapabilities,
    PropertySpec,
)


def test_cli_audit_reconcile_and_plan_with_reconciliation(tmp_path) -> None:
    runner = CliRunner()
    capabilities_path = tmp_path / "portal_capabilities.json"
    audit_path = tmp_path / "crm_audit.yaml"
    design_path = tmp_path / "crm_design.yaml"
    reconciliation_path = tmp_path / "crm_reconciliation.yaml"
    manifest_path = tmp_path / "hubspot_manifest.yaml"
    change_plan_path = tmp_path / "crm_change_plan.md"
    approval_path = tmp_path / "hubspot_manifest.approval.json"
    dry_run_path = tmp_path / "dry_run_report.md"

    capabilities = PortalCapabilities(
        generated_at="2026-06-23T00:00:00+00:00",
        api_version="2026-03",
        objects={
            "companies": PortalObjectCapabilities(
                object_type="companies",
                readable=True,
                writable=True,
                properties={
                    "business_segment": {
                        "name": "business_segment",
                        "label": "Segment",
                        "type": "enumeration",
                        "fieldType": "select",
                        "options": [{"label": "SMB", "value": "smb"}],
                    }
                },
            ),
            "contacts": PortalObjectCapabilities(
                object_type="contacts",
                readable=True,
                writable=True,
                properties={},
            ),
            "deals": PortalObjectCapabilities(
                object_type="deals",
                readable=True,
                writable=True,
                properties={},
                pipelines=[{"id": "default", "label": "Main Sales", "stages": []}],
            ),
        },
    )
    design = CrmDesign(
        generated_at="2026-06-23T00:00:00+00:00",
        project_slug="acme",
        business_name="Acme",
        properties=[
            PropertySpec(
                object_type="companies",
                name="acme_segment",
                label="Segment",
                group_name="companyinformation",
                type="enumeration",
                field_type="select",
                options=[{"label": "SMB", "value": "smb"}],
            )
        ],
        pipelines=[
            PipelineSpec(
                object_type="deals",
                label="Main Sales",
                stages=[PipelineStageSpec(label="New opportunity")],
            )
        ],
    )
    write_json(capabilities_path, capabilities)
    write_yaml(design_path, design)

    audit_result = runner.invoke(
        app,
        [
            "audit",
            "--capabilities",
            str(capabilities_path),
            "--out",
            str(audit_path),
            "--hubs",
            "core",
            "--no-live",
        ],
    )
    assert audit_result.exit_code == 0, audit_result.output

    reconcile_result = runner.invoke(
        app,
        [
            "reconcile",
            "--design",
            str(design_path),
            "--audit",
            str(audit_path),
            "--out",
            str(reconciliation_path),
        ],
    )
    assert reconcile_result.exit_code == 0, reconcile_result.output

    plan_result = runner.invoke(
        app,
        [
            "plan",
            "--design",
            str(design_path),
            "--capabilities",
            str(capabilities_path),
            "--reconciliation",
            str(reconciliation_path),
            "--out",
            str(manifest_path),
        ],
    )
    assert plan_result.exit_code == 0, plan_result.output
    assert manifest_path.exists()

    review_result = runner.invoke(
        app,
        [
            "review-plan",
            "--manifest",
            str(manifest_path),
            "--capabilities",
            str(capabilities_path),
            "--out",
            str(change_plan_path),
        ],
    )
    assert review_result.exit_code == 0, review_result.output
    assert "Plan humano guardado" in review_result.output
    change_plan_text = change_plan_path.read_text(encoding="utf-8")
    assert "Revision humana antes de cambiar HubSpot" in change_plan_text
    assert "Decision requerida" in change_plan_text
    assert "Gates antes de escribir" in change_plan_text
    assert "Apendice tecnico" in change_plan_text
    assert "Manifest hash" in change_plan_text

    validate_result = runner.invoke(
        app,
        [
            "validate",
            "--manifest",
            str(manifest_path),
            "--capabilities",
            str(capabilities_path),
            "--approve",
            "--approval-out",
            str(approval_path),
            "--change-plan",
            str(change_plan_path),
        ],
    )
    assert validate_result.exit_code == 0, validate_result.output
    assert approval_path.exists()

    dry_run_result = runner.invoke(
        app,
        [
            "apply",
            "--manifest",
            str(manifest_path),
            "--approval",
            str(approval_path),
            "--dry-run-report",
            str(dry_run_path),
        ],
    )
    assert dry_run_result.exit_code == 0, dry_run_result.output
    assert "Wrote" in dry_run_result.output
    assert "Dry-run supervisado" in dry_run_path.read_text(encoding="utf-8")


def test_cli_plan_requires_reconciliation(tmp_path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    capabilities_path = tmp_path / "portal_capabilities.json"
    design_path = tmp_path / "crm_design.yaml"
    manifest_path = tmp_path / "hubspot_manifest.yaml"

    capabilities = PortalCapabilities(
        generated_at="2026-06-23T00:00:00+00:00",
        api_version="2026-03",
        objects={
            "companies": PortalObjectCapabilities(
                object_type="companies",
                readable=True,
                writable=True,
                properties={},
            ),
            "contacts": PortalObjectCapabilities(
                object_type="contacts",
                readable=True,
                writable=True,
                properties={},
            ),
            "deals": PortalObjectCapabilities(
                object_type="deals",
                readable=True,
                writable=True,
                properties={},
                pipelines=[],
            ),
        },
    )
    design = CrmDesign(
        generated_at="2026-06-23T00:00:00+00:00",
        project_slug="acme",
        business_name="Acme",
        properties=[
            PropertySpec(
                object_type="companies",
                name="acme_segment",
                label="Segment",
                group_name="companyinformation",
            )
        ],
        pipelines=[],
    )
    write_json(capabilities_path, capabilities)
    write_yaml(design_path, design)

    result = runner.invoke(
        app,
        [
            "plan",
            "--design",
            str(design_path),
            "--capabilities",
            str(capabilities_path),
            "--out",
            str(manifest_path),
        ],
    )

    assert result.exit_code != 0
    assert "Run reconcile before plan" in result.output
    assert not manifest_path.exists()
