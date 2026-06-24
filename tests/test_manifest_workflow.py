from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from crm_agent.apply import assert_approval
from crm_agent.cli import app
from crm_agent.design import build_design
from crm_agent.hubspot import HubSpotConnector
from crm_agent.intake import build_business_context
from crm_agent.models import (
    BusinessContext,
    HubSpotManifest,
    ManifestApproval,
    ManifestOperation,
    PortalCapabilities,
    PortalObjectCapabilities,
)
from crm_agent.planner import build_manifest
from crm_agent.settings import Settings
from crm_agent.validation import validate_manifest


def fake_capabilities() -> PortalCapabilities:
    return PortalCapabilities(
        generated_at="2026-06-23T00:00:00+00:00",
        api_version="2026-03",
        objects={
            "companies": PortalObjectCapabilities(
                object_type="companies",
                readable=True,
                writable=True,
                properties={
                    "name": {"name": "name", "type": "string", "fieldType": "text"},
                    "domain": {"name": "domain", "type": "string", "fieldType": "text"},
                },
            ),
            "contacts": PortalObjectCapabilities(
                object_type="contacts",
                readable=True,
                writable=True,
                properties={"email": {"name": "email", "type": "string", "fieldType": "text"}},
            ),
            "deals": PortalObjectCapabilities(
                object_type="deals",
                readable=True,
                writable=True,
                properties={
                    "dealname": {"name": "dealname", "type": "string", "fieldType": "text"}
                },
                pipelines=[],
            ),
        },
    )


def test_design_namespaces_custom_properties() -> None:
    context = build_business_context(project_slug="Acme CRM", business_name="Acme")
    design = build_design(context, fake_capabilities())

    property_names = {prop.name for prop in design.properties}

    assert "acme_crm_segment" in property_names
    assert "acme_crm_qualification_notes" in property_names


def test_design_uses_discovered_pipeline_stages() -> None:
    context = BusinessContext(
        project_slug="acme",
        business_name="Acme",
        sales_process_notes="Lead to close.",
        pipeline_stages=["Inbound", "Qualified", "Proposal"],
    )
    design = build_design(context, fake_capabilities())

    stage_labels = [stage.label for stage in design.pipelines[0].stages]

    assert stage_labels == ["Inbound", "Qualified", "Proposal", "Closed Won", "Closed Lost"]
    assert design.pipelines[0].stages[-2].closed
    assert design.pipelines[0].stages[-2].probability == "1.0"
    assert design.pipelines[0].stages[-1].closed
    assert design.pipelines[0].stages[-1].probability == "0.0"


def test_plan_generates_manifest_for_missing_property_and_pipeline() -> None:
    context = build_business_context(project_slug="acme", business_name="Acme")
    design = build_design(context, fake_capabilities())
    manifest = build_manifest(design, fake_capabilities())

    planned_actions = {operation.action for operation in manifest.operations}

    assert "ensure_property" in planned_actions
    assert "ensure_pipeline" in planned_actions
    assert manifest.planned_operations


def test_validation_blocks_unprefixed_custom_property() -> None:
    manifest = HubSpotManifest(
        generated_at="2026-06-23T00:00:00+00:00",
        api_version="2026-03",
        project_slug="acme",
        design_hash="design",
        capability_hash="capabilities",
        operations=[
            ManifestOperation(
                id="property:companies:segment",
                action="ensure_property",
                object_type="companies",
                method="POST",
                endpoint="/crm/properties/2026-03/companies",
                payload={
                    "groupName": "companyinformation",
                    "name": "segment",
                    "label": "Segment",
                    "type": "string",
                    "fieldType": "text",
                },
                expected={"name": "segment"},
                rollback="Archive manually.",
            )
        ],
    )

    report = validate_manifest(manifest, fake_capabilities())

    assert not report.passed
    assert any("capability hash" in error for error in report.errors)
    assert any("must start with namespace" in error for error in report.errors)


def test_validation_approves_current_manifest_hash() -> None:
    context = build_business_context(project_slug="acme", business_name="Acme")
    manifest = build_manifest(build_design(context, fake_capabilities()), fake_capabilities())

    report = validate_manifest(manifest, fake_capabilities(), approve=True, approved_by="tests")

    assert report.passed
    assert report.approval is not None
    assert report.approval.manifest_hash == manifest.manifest_hash


def test_approval_rejects_changed_manifest_hash() -> None:
    context = build_business_context(project_slug="acme", business_name="Acme")
    manifest = build_manifest(build_design(context, fake_capabilities()), fake_capabilities())
    approval = ManifestApproval(manifest_hash="wrong", approved_at="2026-06-23T00:00:00+00:00")

    with pytest.raises(Exception, match="Approval hash"):
        assert_approval(manifest, approval)


def test_execute_requires_current_dry_run_report(tmp_path) -> None:
    runner = CliRunner()
    context = build_business_context(project_slug="acme", business_name="Acme")
    manifest = build_manifest(build_design(context, fake_capabilities()), fake_capabilities())
    approval = ManifestApproval(
        manifest_hash=manifest.manifest_hash,
        approved_at="2026-06-23T00:00:00+00:00",
    )
    manifest_path = tmp_path / "hubspot_manifest.yaml"
    approval_path = tmp_path / "hubspot_manifest.approval.json"
    manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")
    approval_path.write_text(approval.model_dump_json(), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "apply",
            "--manifest",
            str(manifest_path),
            "--approval",
            str(approval_path),
            "--execute",
        ],
    )

    assert result.exit_code != 0
    assert "Dry-run report is missing or stale" in result.output


def test_validate_approve_requires_current_change_plan(tmp_path) -> None:
    runner = CliRunner()
    capabilities = fake_capabilities()
    context = build_business_context(project_slug="acme", business_name="Acme")
    manifest = build_manifest(build_design(context, capabilities), capabilities)
    capabilities_path = tmp_path / "portal_capabilities.json"
    manifest_path = tmp_path / "hubspot_manifest.yaml"
    capabilities_path.write_text(capabilities.model_dump_json(), encoding="utf-8")
    manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "validate",
            "--manifest",
            str(manifest_path),
            "--capabilities",
            str(capabilities_path),
            "--approve",
        ],
    )

    assert result.exit_code != 0
    assert "Run review-plan before approval" in result.output


def test_connector_preflight_uses_read_only_endpoints() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/account-info/v3/details":
            return httpx.Response(200, json={"portalId": 123})
        if request.url.path == "/integrations/v1/limit/daily":
            return httpx.Response(200, json={"usageLimit": 250000})
        if request.url.path.endswith("/deals") and "/crm/pipelines/" in request.url.path:
            return httpx.Response(200, json={"results": []})
        if "/crm/properties/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"name": "name", "type": "string", "fieldType": "text"},
                        {"name": "domain", "type": "string", "fieldType": "text"},
                    ]
                },
            )
        return httpx.Response(404, json={"message": "not found"})

    client = httpx.Client(
        base_url="https://api.hubapi.com",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer test"},
    )
    connector = HubSpotConnector(
        Settings(hubspot_private_app_token="test", outdir=Path(".")),
        client=client,
    )

    capabilities = connector.preflight()

    assert capabilities.account["portalId"] == 123
    assert all(method == "GET" for method, _path in seen)
    assert capabilities.objects["companies"].property_count == 2
