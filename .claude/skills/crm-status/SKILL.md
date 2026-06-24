---
description: Resume the HubSpot CRM setup state from local artifacts. Use when the user asks where things stand, what is missing, or how to continue.
---

# CRM Status

Resume from artifacts, not from conversation memory.

1. Run `crm-agent status`.
2. Explain current phase, completed evidence, blockers, and next safe step in Spanish.
3. Call out completed gates, pending gates, pending discovery questions, and stale artifacts.
4. If the user asks for technical detail, run `crm-agent status --technical`.
5. If blockers exist, ask for the specific business decision needed before continuing.
6. If `crm-agent status` asks for `review-plan`, generate or recommend `crm_change_plan.md` before manifest approval.
7. If `crm-agent status` asks for dry-run, generate or recommend `dry_run_report.md` before any `--execute`.
8. If `crm-agent status` asks for verify, run or recommend `crm-agent verify` and summarize `readback_report.md`.

Do not modify files.
Do not run `apply --execute`.
Do not infer missing HubSpot capabilities; rely on `portal_capabilities.json`, `crm_audit.yaml`, and reconciliation artifacts.
