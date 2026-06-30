---
description: Resume the HubSpot CRM setup state from local artifacts. Use when the user asks where things stand, what is missing, or how to continue.
---

# CRM Status

Resume from artifacts, not from conversation memory.

1. Run `crm-agent status`.
2. Start the user-facing answer with the same non-technical frame used by start:
   greeting, what we need first, secure HubSpot access status, next guided step,
   and the promise that nothing changes without a clear plan and explicit approval.
3. Explain current phase, completed evidence, blockers, strategic question, and next safe step in Spanish.
4. Call out what is ready, what is missing, pending discovery questions, and stale items in human language.
5. If the user asks for technical detail, run `crm-agent status --technical`.
6. If blockers exist, ask for the specific business decision needed before continuing.
7. If status asks for plan review, generate or recommend the human-readable plan before approval.
8. If status asks for simulation, generate or recommend the simulation report before any write.
9. If status asks for verify, run or recommend verification and summarize final evidence.

Do not modify files.
Do not run `apply --execute`.
Do not infer missing HubSpot capabilities; rely on `portal_capabilities.json`, `crm_audit.yaml`, and reconciliation artifacts.
Do not surface commands, YAML, JSON, manifests, hashes, file names, tokens, `.env`, or code modules unless the user asks for technical details.
Do not answer "como empiezo" or "ya instale el repo" with terminal commands first; lead with state and the guided next step.
