---
description: Run adaptive business discovery for HubSpot CRM setup. Use after audit exists or when the user is describing their business process.
---

# CRM Discovery

Use an adaptive interview in Spanish.

1. Run `crm-agent status` to understand current artifacts.
2. If `crm_audit.yaml` exists, use it to tailor questions.
3. Use the pending questions reported by status as the first source of truth.
4. Ask one high-value question at a time, not a long form.
5. Early in discovery, ask whether there is a website, spreadsheet, CSV,
   document, or process file that already explains how sales works today.
6. Cover business model, sales process, pipeline stages, required data, reporting, roles, desired hubs, constraints, and existing configuration to preserve.
7. Confirm pipeline stages in business language before design; they become the actual deal pipeline stages.
8. Persist answers with `crm-agent discover` when there is enough information.
9. Use `--website-url` and `--source-file` for supplied sources when available.
10. Produce `crm_setup_spec.md` and ask the user to review the human route before design.
11. Keep technical files as support evidence. The user should not need to read
   YAML or manifests during discovery.

Never create a manifest directly from raw conversation.
Never write to HubSpot from discovery.
Never skip `approve-spec`; the spec approval must match the current hash.
If the user asks a technical question, answer it briefly and return to the guided discovery path.
