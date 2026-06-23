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
