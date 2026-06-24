from __future__ import annotations

from crm_agent.models import HubSpotManifest, ManifestOperation
from crm_agent.verify import verify_manifest


class FakeConnector:
    def get_property(self, object_type: str, property_name: str) -> dict:
        if object_type == "companies" and property_name == "acme_segment":
            return {"name": property_name}
        return {}

    def get_pipelines(self, object_type: str = "deals") -> list[dict]:
        return []


def test_verify_manifest_includes_manifest_hash_and_readback_evidence() -> None:
    manifest = HubSpotManifest(
        generated_at="2026-06-23T00:00:00+00:00",
        api_version="2026-03",
        project_slug="acme",
        design_hash="design",
        capability_hash="capabilities",
        operations=[
            ManifestOperation(
                id="property:companies:acme_segment",
                action="ensure_property",
                object_type="companies",
                method="POST",
                endpoint="/crm/properties/2026-03/companies",
                payload={"name": "acme_segment"},
                rollback="Archive manually.",
            )
        ],
    )

    report = verify_manifest(manifest, FakeConnector())

    assert f"Manifest hash: `{manifest.manifest_hash}`" in report
    assert "Property `acme_segment` exists." in report
