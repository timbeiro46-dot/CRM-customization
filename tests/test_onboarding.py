from __future__ import annotations

from crm_agent.onboarding import V1_RECOMMENDED_SCOPES, legacy_app_setup_text


def test_legacy_app_setup_text_is_explicit_about_required_setup() -> None:
    text = legacy_app_setup_text()

    assert "Legacy private app setup is required before preflight" in text
    assert "Development > Legacy apps" in text
    assert "HUBSPOT_PRIVATE_APP_TOKEN" in text
    assert "Never commit .env" in text


def test_v1_scope_checklist_has_sales_core_read_and_write_scopes() -> None:
    scopes = set(V1_RECOMMENDED_SCOPES)

    assert "crm.objects.companies.read" in scopes
    assert "crm.objects.contacts.write" in scopes
    assert "crm.objects.deals.write" in scopes
    assert "crm.schemas.deals.write" in scopes
