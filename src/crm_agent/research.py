from __future__ import annotations

from crm_agent.constants import OFFICIAL_RESEARCH_SOURCES
from crm_agent.models import SourceRegistry


def build_research_registry() -> SourceRegistry:
    return SourceRegistry(
        generated_from_plan_date="2026-06-23",
        sources=[
            {
                **source,
                "use_for": _use_for(source["id"]),
            }
            for source in OFFICIAL_RESEARCH_SOURCES
        ],
        principles=[
            (
                "Capability discovery must happen before recommendations that depend on "
                "HubSpot tier or scopes."
            ),
            (
                "Direct HubSpot APIs are the source of truth for exact records, "
                "properties, and configuration."
            ),
            (
                "MCP can support future conversational discovery, but V1 writes use "
                "explicit API-backed manifest operations."
            ),
            "All write operations must be idempotent, logged, and verified by readback.",
        ],
    )


def _use_for(source_id: str) -> list[str]:
    mapping = {
        "hubspot_api_overview": ["Date-based API version selection", "Endpoint discovery"],
        "hubspot_apis_by_tier": ["Portal capability gating", "Product tier assumptions"],
        "hubspot_usage_guidelines": ["Rate limit handling", "Retry strategy"],
        "hubspot_oauth": ["Future public distribution path", "Scope design"],
        "hubspot_legacy_private_apps": [
            "MVP authentication setup",
            "User onboarding before preflight",
            "Private app token handling",
        ],
        "hubspot_scopes": [
            "V1 CRM/Sales scope checklist",
            "Scope and tier troubleshooting",
        ],
        "hubspot_mcp": ["Future conversational CRM discovery", "Tool-surface comparison"],
        "hubspot_properties": [
            "Property type and fieldType validation",
            "Unique property constraints",
        ],
        "hubspot_schemas": ["Future custom object gate", "Enterprise-only schema awareness"],
        "hubspot_associations": [
            "Association direction and label validation",
            "Association rate limits",
        ],
        "hubspot_pipelines": ["Deal pipeline/stage creation", "Stage metadata validation"],
        "superpowers": ["Phase-based agent workflow patterns", "Skills/plans/review gates"],
    }
    return mapping[source_id]
