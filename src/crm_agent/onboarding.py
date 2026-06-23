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


def legacy_app_setup_text() -> str:
    scopes = "\n".join(f"  - {scope}" for scope in V1_RECOMMENDED_SCOPES)
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
  8. Create the app.
  9. Open Auth > Show token > Copy.
 10. Paste it into local .env as HUBSPOT_PRIVATE_APP_TOKEN.

Local setup:
  cp .env.example .env
  # edit .env and set HUBSPOT_PRIVATE_APP_TOKEN
  crm-agent preflight --out portal_capabilities.json

Security:
  - Never commit .env.
  - Never paste the token into chat.
  - Do not add non-V1 scopes unless the codebase adds support for them.

Official docs:
  - https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/overview.md
  - https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/scopes.md
"""
