# Supervised HubSpot CRM Agent Runbook

This repo is a Claude-native, supervised agent for HubSpot CRM/Sales
parameterization. It is designed for a non-technical Spanish-speaking user and
for safe handoff through Claude Code and GitHub.

For the human-facing experience contract, use
[guided_experience.md](guided_experience.md).

## Operating Principle

The agent may diagnose, audit, reconcile, and plan autonomously. It must not
write to HubSpot until a human has reviewed the exact plan and approved the
current manifest hash.

Use local artifacts as the source of truth:

- `.crm-agent/session_state.yaml`: current phase, artifact hashes, blockers,
  pending questions, completed gates, pending gates, and next safe action.
- `.crm-agent/progress.md`: durable progress log.
- `.crm-agent/discovery_ledger.md`: discovery/spec handoff history.
- `.crm-agent/approval_ledger.md`: approvals recorded by artifact hash.

Do not answer from conversation memory when these files exist.

## Happy Path

```bash
crm-agent start
crm-agent preflight --out portal_capabilities.json
crm-agent audit --capabilities portal_capabilities.json --out crm_audit.yaml --hubs auto --depth metadata-quality
crm-agent discover --audit crm_audit.yaml
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

The first `apply` command above is a dry-run and writes `dry_run_report.md`. Do
not run `crm-agent apply --execute` unless the user explicitly approves that
exact write step after reviewing the dry-run report.

## Supervision Gates

Before design:

- `business_context.yaml` must reflect the discovery answers.
- `crm_setup_spec.md` must be reviewed by the user.
- `crm_setup_spec.approval.json` must match the current spec hash.
- `crm-agent design` must fail if the spec approval is missing or stale.

Before apply:

- `crm_reconciliation.yaml` must reconcile desired changes against the audit.
- `crm-agent plan` must fail if reconciliation is missing or stale.
- `hubspot_manifest.yaml` must contain only supported V1 operations.
- `crm_change_plan.md` must summarize the current manifest hash in human language.
- `crm-agent validate --approve` must fail if the human change plan is missing or stale.
- `crm-agent validate --approve` must pass.
- `hubspot_manifest.approval.json` must match the current manifest hash.
- `dry_run_report.md` must match the current manifest hash and be reviewed.

After apply:

- `crm-agent verify --manifest hubspot_manifest.yaml --out readback_report.md`
  must read HubSpot back and document evidence.
- `readback_report.md` must reference the current manifest hash before the run is
  considered verified.

## Claude Code Behavior

Start with `/crm-start` or `crm-agent status`. Keep answers in Spanish unless the
user asks otherwise. Name the current phase, give one strategic question or one
safe next action, not a module tour.

Use adaptive discovery:

- Ask one business question at a time unless the user asks for a checklist.
- Prefer business language over API language.
- Ask early for existing context sources such as website, spreadsheet, CSV,
  notes, or XLSX process files; use `--website-url` and `--source-file` when
  persisting discovery.
- Capture roles, sales process, pipeline stages, critical data, weekly reporting,
  desired hubs, constraints, and existing configuration to preserve.
- Confirm the pipeline stages before design; `crm-agent design` uses the
  discovered stages and appends closed-won/lost exits when missing.
- Use `crm_audit.yaml` to ask what existing assets should be preserved.
- Persist discovery through `crm-agent discover`, then route to spec review.
- Keep human review on `crm_setup_spec.md`, `crm_change_plan.md`,
  `dry_run_report.md`, and `readback_report.md`; keep YAML/JSON/manifests as
  support evidence unless the user asks for technical detail.

If `status` reports stale artifacts, rerun the relevant reconcile, review,
validation, dry-run, or readback step instead of continuing downstream.
If `status` asks for `review-plan`, generate `crm_change_plan.md` and use it as
the document the user reviews before manifest approval.
If `status` asks for dry-run, run `crm-agent apply` without `--execute` and have
the user review `dry_run_report.md` before asking for write approval.
If `status` asks for verify, run readback and answer from `readback_report.md`
rather than from the apply log alone.

## GitHub Handoff Checklist

Before opening or reviewing a PR:

- Run `.venv/bin/python -m pytest`.
- Run `.venv/bin/python -m ruff check .`.
- Include updates to `README.md`, `CLAUDE.md`, and this runbook when changing the
  supervised workflow.
- Do not commit `.env`, generated CRM artifacts, `.crm-agent/`, or HubSpot tokens.
- In the PR description, state which supervision gates changed and what evidence
  proves the change.
