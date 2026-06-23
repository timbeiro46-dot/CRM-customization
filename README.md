# HubSpot CRM Agent

Supervised toolkit for parameterizing HubSpot CRM/Sales portals through a safe,
phase-based workflow. The MVP uses a legacy private app token, but the code keeps
HubSpot access behind a connector boundary so OAuth or MCP-backed discovery can be
added later.

## What V1 Covers

- CRM/Sales core only: companies, contacts, deals, properties, deal pipelines,
  stages, and basic associations.
- Standard objects first. Custom objects are intentionally gated for future work.
- No hard deletes, no workflows, no reports, no dashboards, no campaigns, no forms,
  and no permissions automation in V1.
- Every write path requires a manifest, validation, approval by manifest hash, and
  explicit `--execute`.

## Quickstart

Before running the agent, configure the HubSpot legacy private app. This is not
optional in the MVP.

```bash
crm-agent setup-legacy-app
```

The short version:

- A HubSpot super admin must go to **Development** > **Legacy apps**.
- Create a legacy app of type **Private**.
- Add the CRM/Sales core scopes in
  [docs/legacy_private_app_setup.md](docs/legacy_private_app_setup.md).
- Copy the token from the app's **Auth** tab.
- Paste it into `.env` as `HUBSPOT_PRIVATE_APP_TOKEN`.

Then set up the local project:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Then fill `HUBSPOT_PRIVATE_APP_TOKEN` in `.env` and run `preflight`.

## Workflow

```bash
crm-agent preflight --out portal_capabilities.json
crm-agent intake --project-slug acme --business-name "Acme" --out business_context.yaml
crm-agent design --context business_context.yaml --capabilities portal_capabilities.json --out crm_design.yaml
crm-agent plan --design crm_design.yaml --capabilities portal_capabilities.json --out hubspot_manifest.yaml
crm-agent validate --manifest hubspot_manifest.yaml --capabilities portal_capabilities.json --approve
crm-agent apply --manifest hubspot_manifest.yaml --approval hubspot_manifest.approval.json
crm-agent apply --manifest hubspot_manifest.yaml --approval hubspot_manifest.approval.json --execute
crm-agent verify --manifest hubspot_manifest.yaml --out readback_report.md
```

`apply` defaults to dry-run. It will not write to HubSpot unless `--execute` is
provided and the approval file matches the current manifest hash.

## Safety Contract

- Tokens are loaded from local environment only and are redacted in logs.
- `preflight`, `intake`, `design`, `plan`, `validate`, and `verify` are read-only.
- `apply` supports only idempotent create/update operations implemented in
  `HubSpotConnector`; destructive `DELETE` operations are blocked.
- Manifest operations must use relative HubSpot API paths, declared risk, rollback
  notes, and namespace-safe property names.

## Research Sources

The current source registry lives in [docs/research_registry.yaml](docs/research_registry.yaml).
Refresh it with:

```bash
crm-agent research-registry --out docs/research_registry.yaml
```

## Tests

```bash
pytest
```
