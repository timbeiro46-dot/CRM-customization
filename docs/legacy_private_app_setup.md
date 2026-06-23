# Legacy Private App Setup

Before running `crm-agent preflight`, each HubSpot portal must have a legacy
private app configured by a HubSpot super admin.

HubSpot's documentation says legacy private apps are still supported, but do not
have access to the latest app features. For this MVP, the private app is the
required connection method.

## Create The App In HubSpot

1. Log in to the target HubSpot account as a super admin.
2. Go to **Development**.
3. Open **Legacy apps** from the left sidebar.
4. Click **Create legacy app**.
5. Choose **Private**.
6. Fill the app name and description.
7. Open the **Scopes** tab.
8. Click **Add new scope** and add the V1 scopes below.
9. Click **Create app**.
10. Open the app's **Auth** tab.
11. Click **Show token**, then **Copy**.
12. Paste the token into a local `.env` file as `HUBSPOT_PRIVATE_APP_TOKEN`.

Never commit `.env` or paste the token into chat.

## Recommended V1 Scopes

CRM/Sales core:

- `crm.objects.companies.read`
- `crm.objects.companies.write`
- `crm.objects.contacts.read`
- `crm.objects.contacts.write`
- `crm.objects.deals.read`
- `crm.objects.deals.write`
- `crm.schemas.companies.read`
- `crm.schemas.companies.write`
- `crm.schemas.contacts.read`
- `crm.schemas.contacts.write`
- `crm.schemas.deals.read`
- `crm.schemas.deals.write`

Do not add custom object, workflow, marketing, service, report, dashboard, form,
or user-management scopes for V1 unless the codebase explicitly adds support for
those features later.

## Local `.env`

```bash
cp .env.example .env
```

Then edit `.env`:

```env
HUBSPOT_PRIVATE_APP_TOKEN=pat-na1-REPLACE_ME
```

## First Verification

```bash
crm-agent setup-legacy-app
crm-agent preflight --out portal_capabilities.json
```

`preflight` is read-only. It validates that the token works and records the
current portal capability snapshot before any design or write plan is created.

## Official References

- HubSpot legacy private apps: https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/overview.md
- HubSpot scopes: https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/scopes.md
- HubSpot API usage guidelines: https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines.md
