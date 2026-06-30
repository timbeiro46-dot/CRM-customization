# HubSpot CRM Agent

Guided agent for adapting HubSpot CRM/Sales portals through a safe, phase-based
workflow. It is designed for a non-technical Spanish-speaking user: the agent
leads the route, asks one strategic question at a time, adapts to the existing
portal and available plan, and keeps all HubSpot writes behind human gates.

The MVP uses a legacy private app token, but the code keeps HubSpot access behind
a connector boundary so OAuth or MCP-backed discovery can be added later.

## What V1 Covers

- CRM/Sales core only: companies, contacts, deals, properties, deal pipelines,
  stages, and basic associations.
- Read-only deep audit can inspect additional hubs when the portal plan and
  private-app scopes expose them. Optional hubs degrade gracefully when unavailable.
- Standard objects first. Custom objects are intentionally gated for future work.
- No hard deletes, no workflows, no reports, no dashboards, no campaigns, no forms,
  and no permissions automation in V1.
- Every write path requires a manifest, validation, approval by manifest hash, and
  explicit `--execute`.

## Quickstart

Start with the guided experience. The first answer is always conversational and
non-technical. It explains what we need first, whether it is already ready, what
is missing, and the next guided step in Spanish:

```bash
crm-agent start
```

The normal first screen should feel like this:

```text
Hola, soy tu agente de configuracion CRM.

Primero necesitamos conectar HubSpot de forma segura para poder revisar tu portal.
Estado actual: todavia no tenemos acceso seguro a HubSpot.
Si no esta conectado, te guio paso a paso.
No voy a cambiar nada en HubSpot sin mostrarte un plan claro y pedirte aprobacion.
```

If this is a new machine or portal, the first human step is creating secure
HubSpot access with a super admin. The agent explains that in plain language
first. It does not show terminal commands, file names, tokens, manifests, hashes,
or apply commands unless the user asks for technical/operator detail.

## Operator Setup

For an operator installing or wiring the repo, the technical setup is:

```bash
crm-agent setup-legacy-app
```

The short version of the HubSpot setup:

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

Then fill `HUBSPOT_PRIVATE_APP_TOKEN` in `.env` and run `crm-agent start` again.

## Workflow

Recommended user-facing flow:

```bash
crm-agent start
crm-agent status
crm-agent discover --audit crm_audit.yaml
crm-agent approve-spec --spec crm_setup_spec.md
```

The human experience is:

1. Connect: configure safe local access.
2. Read: inspect portal capabilities and existing CRM configuration.
3. Discover: answer business questions one at a time.
4. Design: generate a CRM proposal from the approved diagnosis.
5. Review: read a human plan before approving a manifest hash.
6. Simulate: run dry-run and review `dry_run_report.md`.
7. Apply: write only after explicit `--execute` approval.
8. Verify: read HubSpot back and close with evidence.

For the Claude Code/GitHub operating contract, see
[docs/supervised_agent_runbook.md](docs/supervised_agent_runbook.md).
For the zero-technical user flow, see
[docs/guided_experience.md](docs/guided_experience.md).

Advanced operator flow:

```bash
crm-agent preflight --out portal_capabilities.json
crm-agent audit --capabilities portal_capabilities.json --out crm_audit.yaml --hubs auto --depth metadata-quality
crm-agent discover --audit crm_audit.yaml --out business_context.yaml --spec-out crm_setup_spec.md
crm-agent approve-spec --spec crm_setup_spec.md
crm-agent design --context business_context.yaml --capabilities portal_capabilities.json --out crm_design.yaml
crm-agent reconcile --design crm_design.yaml --audit crm_audit.yaml --out crm_reconciliation.yaml
crm-agent plan --design crm_design.yaml --capabilities portal_capabilities.json --reconciliation crm_reconciliation.yaml --out hubspot_manifest.yaml
crm-agent review-plan --manifest hubspot_manifest.yaml --capabilities portal_capabilities.json --out crm_change_plan.md
crm-agent validate --manifest hubspot_manifest.yaml --capabilities portal_capabilities.json --approve
crm-agent apply --manifest hubspot_manifest.yaml --approval hubspot_manifest.approval.json
crm-agent apply --manifest hubspot_manifest.yaml --approval hubspot_manifest.approval.json --execute
crm-agent verify --manifest hubspot_manifest.yaml --out readback_report.md
```

`audit` is read-only. It stores metadata, counts, aggregate fill rates, enum option
usage counts, and findings. It does not export full contact/company/deal values.
If no token is present, it still writes a capabilities-only audit and marks
`live_enrichment: false`.

`reconcile` compares the desired design against the audited portal and can decide
to reuse, create, extend, block, or require review. `plan` requires a
`crm_reconciliation.yaml` file and rejects stale reconciliation when the design
or capability hashes no longer match.

`discover` asks for business model, roles, sales process, pipeline stages,
critical data, reporting goals, desired hubs, constraints, and optional context
sources such as a website, CSV, TSV, text/Markdown notes, or XLSX process file.
It writes a business context and a human-readable `crm_setup_spec.md`. Review
and approve that spec before generating the technical CRM design.
`start` and `status` also surface the current supervision gates, pending discovery
questions, and stale artifacts from local files.
The CLI keeps the human experience separate from technical artifacts: users
review `crm_setup_spec.md`, `crm_change_plan.md`, `dry_run_report.md`, and
`readback_report.md`; YAML and JSON files remain support evidence unless a
technical operator asks for them.
Optional context sources can be passed directly:

```bash
crm-agent discover --audit crm_audit.yaml \
  --website-url https://example.com \
  --source-file proceso_ventas.xlsx
```

`design` refuses to run unless `crm_setup_spec.approval.json` matches the current
`crm_setup_spec.md`.
`review-plan` translates the technical manifest into `crm_change_plan.md`, a
human-readable plan with validation status, risks, rollback notes, blockers, and
the exact dry-run/write commands.
`validate --approve` refuses to create `hubspot_manifest.approval.json` unless
`crm_change_plan.md` matches the current manifest hash.
`apply` without `--execute` writes `dry_run_report.md`. `apply --execute` refuses
to run unless that dry-run report matches the current manifest hash.
`verify` writes `readback_report.md`; `status` treats it as final evidence only
when it references the current manifest hash.

`apply` defaults to dry-run. It will not write to HubSpot unless `--execute` is
provided and the approval file matches the current manifest hash.

## Persistent Agent Memory

The agent uses filesystem memory instead of chat memory for resumability:

- `.crm-agent/session_state.yaml` records phase, artifact hashes, blockers, gates,
  and the next safe action.
- `.crm-agent/progress.md` records durable progress events.
- `.crm-agent/discovery_ledger.md` records discovery/spec handoffs.
- `.crm-agent/approval_ledger.md` records spec and manifest approvals by artifact
  hash.
- `crm_change_plan.md` is the human change plan. It is considered current only
  when it references the current manifest hash.
- `dry_run_report.md` records the supervised dry-run and is required before
  `apply --execute`.
- `readback_report.md` records post-write evidence and must match the current
  manifest hash.

If base artifacts change after downstream gates, the agent marks the affected
spec approval, reconciliation, change plan, dry-run, or readback evidence stale
and routes back to the safe review step.

## Safety Contract

- Tokens are loaded from local environment only and are redacted in logs.
- `preflight`, `intake`, `audit`, `discover`, `status`, `design`, `reconcile`,
  `plan`, `validate`, and `verify` are read-only.
- `apply` supports only idempotent create/update operations implemented in
  `HubSpotConnector`; destructive `DELETE` operations are blocked.
- Manifest operations must use relative HubSpot API paths, declared risk, rollback
  notes, and namespace-safe property names.
- Existing CRM configuration is never overwritten automatically. Conflicting
  existing properties or medium-confidence fuzzy matches become blockers until a
  human resolves the decision.
- Claude Code users should start with `/crm-start` or ask the agent to run
  `crm-agent start`. The project includes `CLAUDE.md` and CRM skills that keep
  the assistant in consultant mode instead of explaining code internals.

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
