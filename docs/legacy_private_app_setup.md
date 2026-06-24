# Legacy Private App Setup

Before running `crm-agent start`, each HubSpot portal must have a legacy
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

These read/write scopes are enough for the V1 Sales-core apply workflow.

## Optional Read Scopes For Deep Audit

`crm-agent audit --hubs auto` is still read-only, but it can inspect more of the
portal when the private app has additional read scopes. Add only the scopes for
the hubs you actually want to audit:

- Sales add-ons: `crm.objects.leads.read`, `crm.objects.line_items.read`,
  `crm.objects.quotes.read`
- Service: `crm.objects.tickets.read`
- Marketing metadata: `crm.objects.marketing_events.read`
- Commerce/revenue objects: `crm.objects.invoices.read`, `crm.objects.orders.read`,
  `crm.objects.subscriptions.read`
- Content metadata: `content.read`
- Enterprise/customization discovery: `crm.schemas.custom.read`

Do not add workflow, report, dashboard, form, permission, or write scopes for
optional hubs unless the codebase explicitly adds supervised support for those
features later. If a scope or hub is missing, audit records `not_available` with
the exact API error instead of failing the whole run.

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
crm-agent start
```

`start` will tell the user the next safe step. The first technical steps are
`preflight` and `audit`; both are read-only. `preflight` validates that the token
works and records the current portal capability snapshot. `audit` then records
existing configuration, availability by hub, and aggregate data-quality signals
before any design or write plan is created.

## Official References

- HubSpot legacy private apps: https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/overview.md
- HubSpot scopes: https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/scopes.md
- HubSpot API usage guidelines: https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines.md
