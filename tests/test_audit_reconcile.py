from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from crm_agent.audit import build_audit
from crm_agent.audit_registry import select_audit_modules
from crm_agent.hubspot import HubSpotConnector
from crm_agent.models import (
    CrmDesign,
    PipelineSpec,
    PipelineStageSpec,
    PortalCapabilities,
    PortalObjectCapabilities,
    PropertySpec,
)
from crm_agent.planner import build_manifest
from crm_agent.reconcile import reconcile_design_with_audit
from crm_agent.settings import Settings
from crm_agent.validation import validate_manifest


def capabilities_with_existing_assets() -> PortalCapabilities:
    return PortalCapabilities(
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
                        "options": [
                            {"label": "SMB", "value": "smb"},
                            {"label": "Enterprise", "value": "enterprise"},
                        ],
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
                pipelines=[
                    {
                        "id": "default",
                        "label": "Main Sales",
                        "stages": [
                            {"id": "new", "label": "New opportunity"},
                        ],
                    }
                ],
            ),
        },
    )


def design_for_reconciliation() -> CrmDesign:
    return CrmDesign(
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
                options=[
                    {"label": "SMB", "value": "smb"},
                    {"label": "Enterprise", "value": "enterprise"},
                ],
            )
        ],
        pipelines=[
            PipelineSpec(
                object_type="deals",
                label="Main Sales",
                stages=[
                    PipelineStageSpec(label="New opportunity"),
                    PipelineStageSpec(label="Qualified", probability="0.3", display_order=1),
                ],
            )
        ],
    )


def test_audit_can_run_from_capabilities_without_live_token() -> None:
    audit = build_audit(capabilities_with_existing_assets(), hubs="auto")

    assert not audit.live_enrichment
    assert audit.capability_hash
    assert audit.objects["companies"].property_count == 1
    assert audit.hubs["content"].availability.status == "not_available"


def test_hub_selection_supports_explicit_modules() -> None:
    modules = select_audit_modules("core,service")

    assert [module.hub for module in modules] == ["core", "service"]


def test_connector_read_only_guard_blocks_mutating_audit_calls() -> None:
    connector = HubSpotConnector(Settings(hubspot_private_app_token="test", outdir=Path(".")))

    with pytest.raises(Exception, match="read-only guard"):
        connector._read_only_request("PATCH", "/crm/properties/2026-03/companies/name")

    connector.close()


def test_live_audit_uses_read_only_methods_and_search_post_only() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if "/groups" in request.url.path:
            return httpx.Response(200, json={"results": []})
        if "/crm/pipelines/" in request.url.path:
            return httpx.Response(200, json={"results": []})
        if "/crm/associations/" in request.url.path:
            return httpx.Response(200, json={"results": []})
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"total": 1, "results": [{"properties": {}}]})
        if "/crm/properties/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "name": "business_segment",
                            "label": "Segment",
                            "type": "enumeration",
                            "fieldType": "select",
                            "options": [{"label": "SMB", "value": "smb"}],
                        }
                    ]
                },
            )
        return httpx.Response(404, json={"message": "not found"})

    client = httpx.Client(
        base_url="https://api.hubapi.com",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer test"},
    )
    connector = HubSpotConnector(Settings(hubspot_private_app_token="test"), client=client)

    audit = build_audit(
        capabilities_with_existing_assets(),
        connector=connector,
        hubs="core",
        sample_limit=1,
    )

    assert audit.live_enrichment
    assert all(method == "GET" or path.endswith("/search") for method, path in seen)


def test_read_only_search_retries_after_429() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"message": "slow"})
        return httpx.Response(200, json={"total": 0, "results": []})

    client = httpx.Client(
        base_url="https://api.hubapi.com",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer test"},
    )
    connector = HubSpotConnector(
        Settings(hubspot_private_app_token="test", max_retries=2),
        client=client,
    )

    result = connector.search_object_sample("companies", properties=["name"], limit=1)

    assert result["total"] == 0
    assert calls == 2


def test_reconciliation_reuses_compatible_existing_property_and_extends_pipeline() -> None:
    capabilities = capabilities_with_existing_assets()
    audit = build_audit(capabilities, hubs="core")
    design = design_for_reconciliation()

    reconciliation = reconcile_design_with_audit(design, audit)
    decisions = {decision.kind: decision for decision in reconciliation.decisions}

    assert decisions["property"].decision == "reuse_existing"
    assert decisions["property"].existing_name == "business_segment"
    assert decisions["pipeline"].decision == "extend_existing"

    manifest = build_manifest(design, capabilities, reconciliation)
    actions = {operation.action for operation in manifest.operations}

    assert "ensure_property" not in actions
    assert "ensure_pipeline_stage" in actions


def test_reconciliation_blocks_conflicting_property_shape() -> None:
    capabilities = capabilities_with_existing_assets()
    audit = build_audit(capabilities, hubs="core")
    design = design_for_reconciliation()
    design.properties[0].type = "string"
    design.properties[0].field_type = "text"

    reconciliation = reconcile_design_with_audit(design, audit)
    manifest = build_manifest(design, capabilities, reconciliation)
    report = validate_manifest(manifest, capabilities)

    assert reconciliation.decisions[0].decision == "blocked_conflict"
    assert not report.passed
    assert any("blocked" in error for error in report.errors)


def test_plan_rejects_stale_reconciliation() -> None:
    capabilities = capabilities_with_existing_assets()
    audit = build_audit(capabilities, hubs="core")
    design = design_for_reconciliation()
    reconciliation = reconcile_design_with_audit(design, audit)
    reconciliation.design_hash = "stale"

    with pytest.raises(ValueError, match="design hash"):
        build_manifest(design, capabilities, reconciliation)
