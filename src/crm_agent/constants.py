from __future__ import annotations

SUPPORTED_OBJECTS = {"companies", "contacts", "deals"}
SUPPORTED_PROPERTY_TYPES = {"bool", "enumeration", "date", "datetime", "string", "number"}
SUPPORTED_FIELD_TYPES = {
    "booleancheckbox",
    "calculation_equation",
    "checkbox",
    "date",
    "file",
    "html",
    "number",
    "phonenumber",
    "radio",
    "select",
    "text",
    "textarea",
}

READ_ONLY_COMMANDS = {"preflight", "intake", "design", "plan", "validate", "verify"}
MUTATING_METHODS = {"POST", "PATCH", "PUT"}
BLOCKED_METHODS = {"DELETE"}

STANDARD_PROPERTY_ALLOWLIST = {
    "companies": {
        "name",
        "domain",
        "industry",
        "numberofemployees",
        "annualrevenue",
        "city",
        "state",
        "country",
        "hubspot_owner_id",
    },
    "contacts": {
        "email",
        "firstname",
        "lastname",
        "phone",
        "mobilephone",
        "jobtitle",
        "hubspot_owner_id",
    },
    "deals": {
        "dealname",
        "dealstage",
        "pipeline",
        "amount",
        "closedate",
        "hubspot_owner_id",
        "dealtype",
    },
}

DEFAULT_DEAL_STAGES = [
    {"label": "New opportunity", "probability": "0.10", "closed": False},
    {"label": "Qualified", "probability": "0.30", "closed": False},
    {"label": "Proposal sent", "probability": "0.60", "closed": False},
    {"label": "Negotiation", "probability": "0.80", "closed": False},
    {"label": "Closed Won", "probability": "1.0", "closed": True},
    {"label": "Closed Lost", "probability": "0.0", "closed": True},
]

OFFICIAL_RESEARCH_SOURCES = [
    {
        "id": "hubspot_api_overview",
        "name": "HubSpot API reference/versioning",
        "url": "https://developers.hubspot.com/docs/api-reference/latest/overview",
    },
    {
        "id": "hubspot_apis_by_tier",
        "name": "HubSpot APIs by tier",
        "url": "https://developers.hubspot.com/docs/developer-tooling/platform/apis-by-tier.md",
    },
    {
        "id": "hubspot_usage_guidelines",
        "name": "HubSpot API usage guidelines",
        "url": "https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines.md",
    },
    {
        "id": "hubspot_oauth",
        "name": "HubSpot OAuth",
        "url": "https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/oauth/working-with-oauth.md",
    },
    {
        "id": "hubspot_legacy_private_apps",
        "name": "HubSpot legacy private apps",
        "url": "https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/overview.md",
    },
    {
        "id": "hubspot_scopes",
        "name": "HubSpot app scopes",
        "url": "https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/scopes.md",
    },
    {
        "id": "hubspot_mcp",
        "name": "HubSpot MCP server",
        "url": "https://developers.hubspot.com/docs/apps/developer-platform/build-apps/integrate-with-the-remote-hubspot-mcp-server.md",
    },
    {
        "id": "hubspot_properties",
        "name": "HubSpot CRM properties",
        "url": "https://developers.hubspot.com/docs/api-reference/latest/crm/properties/guide.md",
    },
    {
        "id": "hubspot_schemas",
        "name": "HubSpot schemas/custom objects",
        "url": "https://developers.hubspot.com/docs/api-reference/latest/crm/objects/schemas/guide.md",
    },
    {
        "id": "hubspot_associations",
        "name": "HubSpot associations",
        "url": "https://developers.hubspot.com/docs/api-reference/latest/crm/associations/associate-records/guide.md",
    },
    {
        "id": "hubspot_pipelines",
        "name": "HubSpot pipelines",
        "url": "https://developers.hubspot.com/docs/api-reference/latest/crm/pipelines/guide.md",
    },
    {
        "id": "superpowers",
        "name": "obra/superpowers",
        "url": "https://github.com/obra/superpowers",
    },
]
