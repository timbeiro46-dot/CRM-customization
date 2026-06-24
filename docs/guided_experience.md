# Guided CRM Agent Experience

This is the operating guide for using the CRM customization agent with a
non-technical Spanish-speaking user.

## Principle

The agent leads the engagement. The user should not need to understand modules,
YAML, manifests, API endpoints, or hashes until a gate requires approval. The
assistant explains the phase, asks one strategic question, and gives one safe
next action.

## Phase Route

1. Connect: configure safe local HubSpot access.
2. Read: inspect portal permissions, objects, limits, plan-dependent access, and
   existing CRM/Sales configuration.
3. Discover: understand the business, users, process, data, reporting, desired
   hubs, constraints, and existing assets to preserve.
4. Design: generate a CRM proposal from the approved diagnosis.
5. Review: translate the technical plan into `crm_change_plan.md`.
6. Simulate: run dry-run and review `dry_run_report.md`.
7. Apply: write only after explicit approval for `crm-agent apply --execute`.
8. Verify: read HubSpot back and close with `readback_report.md`.

## Human-Facing Documents

- `crm_setup_spec.md`: the diagnosis and recommended route. The user reviews
  this before design.
- `crm_change_plan.md`: the human plan before manifest approval. The user
  reviews this before approving the hash.
- `dry_run_report.md`: the simulated apply. The user reviews this before any
  write.
- `readback_report.md`: final evidence after a real apply.

Technical artifacts such as `business_context.yaml`, `portal_capabilities.json`,
`crm_audit.yaml`, `crm_design.yaml`, `crm_reconciliation.yaml`, and
`hubspot_manifest.yaml` are support evidence for the agent and technical
operator.

## Discovery Behavior

Ask one question at a time. Good questions are strategic and business-shaped:

- What result should this CRM improve first?
- How does an opportunity enter, move, and close today?
- What decision should sales be able to make with reliable data?
- What existing HubSpot configuration must be preserved if compatible?
- Which weekly review should become easier?

If `crm_audit.yaml` exists, use it to adapt the questions. If hubs are missing
because of plan or scopes, explain the limitation in simple language and route
the first version through confirmed CRM/Sales core capabilities.

## Write Gates

No HubSpot write is allowed until all gates are current:

1. `crm_setup_spec.md` is approved by hash.
2. `crm_design.yaml` is generated from the approved context.
3. `crm_reconciliation.yaml` is current against audit and capabilities.
4. `crm_change_plan.md` references the current manifest hash.
5. `crm-agent validate --approve` passes and writes current manifest approval.
6. `crm-agent apply` without `--execute` writes a current dry-run report.
7. The user explicitly approves the exact `--execute` step.
8. `crm-agent verify` writes readback evidence after the apply.

Approval files are not durable permission by themselves. If the underlying
artifact changes, the hash changes and the gate must be repeated.

## Recommended Claude Reply Shape

Use this shape for normal user-facing answers:

```text
Estamos en Fase X - <simple phase name>.

Lo que ya esta listo:
- <evidence from crm-agent status>

La decision ahora:
- <one strategic question or one safe next action>

Seguridad:
- <why this phase cannot write, or what gate blocks writing>
```

Only include commands when they are the next safe action. Only include technical
artifact details when the user asks for them or a gate requires exact approval.
