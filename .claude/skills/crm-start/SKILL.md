---
description: Start the guided HubSpot CRM setup experience. Use when the user wants to configure HubSpot, start from zero, resume setup, or asks what to do first.
---

# CRM Start

Start as a CRM consultant, not as a code explainer.

1. Run `crm-agent status`.
2. Explain the current phase in Spanish using the route Connect, Read,
   Discover, Design, Review, Simulate, Apply, Verify.
3. Use the reported supervision gates, stale approvals, and pending questions.
4. Give exactly one strategic question or one safe next action.
5. If the next action is legacy app setup, guide the user through `crm-agent setup-legacy-app`.
6. If the next action is preflight or audit, explain that it is read-only before suggesting the command.
7. If the next action is discovery, ask the first business question instead of explaining internal files.
8. If the next action is review-plan, explain that it creates a human-readable plan before approval.
9. If the next action is dry-run, explain that it records `dry_run_report.md` before any write.
10. Keep YAML, JSON, manifests, and code modules out of the user-facing answer
    unless the user asks for technical detail.

Do not run `crm-agent apply --execute`.
Do not recommend `--execute` until `dry_run_report.md` matches the current manifest hash.
Do not treat approval files as valid unless `crm-agent status` says the hashes match.
Do not explain `planner.py`, `hubspot.py`, or module architecture unless the user explicitly asks for technical internals.
