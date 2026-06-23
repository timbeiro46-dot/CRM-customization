from __future__ import annotations

V1_RECOMMENDED_SCOPES = [
    "crm.objects.companies.read",
    "crm.objects.companies.write",
    "crm.objects.contacts.read",
    "crm.objects.contacts.write",
    "crm.objects.deals.read",
    "crm.objects.deals.write",
    "crm.schemas.companies.read",
    "crm.schemas.companies.write",
    "crm.schemas.contacts.read",
    "crm.schemas.contacts.write",
    "crm.schemas.deals.read",
    "crm.schemas.deals.write",
]

OPTIONAL_AUDIT_SCOPES = [
    "crm.objects.leads.read",
    "crm.objects.line_items.read",
    "crm.objects.quotes.read",
    "crm.objects.tickets.read",
    "crm.objects.marketing_events.read",
    "crm.objects.invoices.read",
    "crm.objects.orders.read",
    "crm.objects.subscriptions.read",
    "content.read",
    "crm.schemas.custom.read",
]


def legacy_app_setup_text() -> str:
    scopes = "\n".join(f"  - {scope}" for scope in V1_RECOMMENDED_SCOPES)
    audit_scopes = "\n".join(f"  - {scope}" for scope in OPTIONAL_AUDIT_SCOPES)
    return f"""Legacy private app setup is required before preflight.

HubSpot setup:
  1. Log in to the target HubSpot account as a super admin.
  2. Go to Development > Legacy apps.
  3. Click Create legacy app.
  4. Choose Private.
  5. Fill name and description.
  6. Open Scopes > Add new scope.
  7. Add these V1 CRM/Sales core scopes:
{scopes}
  8. Optional for deep read-only audit, add only the hub scopes you want:
{audit_scopes}
  9. Create the app.
 10. Open Auth > Show token > Copy.
 11. Paste it into local .env as HUBSPOT_PRIVATE_APP_TOKEN.

Local setup:
  cp .env.example .env
  # edit .env and set HUBSPOT_PRIVATE_APP_TOKEN
  crm-agent preflight --out portal_capabilities.json
  crm-agent audit --capabilities portal_capabilities.json --out crm_audit.yaml

Security:
  - Never commit .env.
  - Never paste the token into chat.
  - Optional audit scopes are read-only and degrade gracefully when unavailable.
  - Do not add optional write scopes unless the codebase adds support for them.

Official docs:
  - https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/overview.md
  - https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/scopes.md
"""
