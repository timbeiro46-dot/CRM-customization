from __future__ import annotations

from dataclasses import dataclass

from crm_agent.constants import CORE_AUDIT_OBJECTS


@dataclass(frozen=True)
class AuditModule:
    hub: str
    object_types: tuple[str, ...] = ()
    required_scopes: tuple[str, ...] = ()
    endpoints: tuple[str, ...] = ()
    quality_checks: tuple[str, ...] = ("metadata", "sample_fill_rate")
    fallback: str = "record not_available with evidence and continue"
    pipelines_supported: tuple[str, ...] = ()


AUDIT_REGISTRY: dict[str, AuditModule] = {
    "core": AuditModule(
        hub="core",
        object_types=CORE_AUDIT_OBJECTS,
        required_scopes=(
            "crm.objects.companies.read",
            "crm.objects.contacts.read",
            "crm.objects.deals.read",
            "crm.schemas.companies.read",
            "crm.schemas.contacts.read",
            "crm.schemas.deals.read",
        ),
        endpoints=(
            "/account-info/v3/details",
            "/crm/properties/{api_version}/{object_type}",
            "/crm/properties/{api_version}/{object_type}/groups",
            "/crm/pipelines/{api_version}/{object_type}",
            "/crm/associations/{api_version}/{from_object}/{to_object}/labels",
            "/crm/objects/{object_type}/search",
        ),
        pipelines_supported=("deals",),
    ),
    "sales": AuditModule(
        hub="sales",
        object_types=("leads", "products", "line_items", "quotes"),
        required_scopes=(
            "crm.objects.leads.read",
            "crm.objects.line_items.read",
            "crm.objects.quotes.read",
        ),
        endpoints=(
            "/crm/properties/{api_version}/{object_type}",
            "/crm/objects/{object_type}/search",
        ),
    ),
    "service": AuditModule(
        hub="service",
        object_types=("tickets", "feedback_submissions"),
        required_scopes=("crm.objects.tickets.read",),
        endpoints=(
            "/crm/properties/{api_version}/{object_type}",
            "/crm/pipelines/{api_version}/tickets",
            "/crm/objects/{object_type}/search",
        ),
        pipelines_supported=("tickets",),
    ),
    "marketing": AuditModule(
        hub="marketing",
        object_types=("marketing_events",),
        required_scopes=("crm.objects.marketing_events.read",),
        endpoints=(
            "/crm/properties/{api_version}/{object_type}",
            "/crm/objects/{object_type}/search",
            "/marketing/v3/forms",
            "/marketing/v3/lists",
        ),
    ),
    "content": AuditModule(
        hub="content",
        object_types=(),
        required_scopes=("content.read",),
        endpoints=(
            "/cms/v3/domains",
            "/cms/v3/blogs",
            "/cms/v3/pages/site-pages",
            "/cms/v3/pages/landing-pages",
        ),
        quality_checks=("metadata",),
    ),
    "commerce": AuditModule(
        hub="commerce",
        object_types=("invoices", "orders", "payments", "subscriptions", "products", "line_items"),
        required_scopes=(
            "crm.objects.invoices.read",
            "crm.objects.orders.read",
            "crm.objects.subscriptions.read",
        ),
        endpoints=(
            "/crm/properties/{api_version}/{object_type}",
            "/crm/objects/{object_type}/search",
        ),
    ),
    "customization": AuditModule(
        hub="customization",
        object_types=(),
        required_scopes=("crm.schemas.custom.read",),
        endpoints=("/crm-object-schemas/{api_version}/schemas",),
        quality_checks=("metadata",),
    ),
}


def select_audit_modules(hubs: str) -> list[AuditModule]:
    requested = [item.strip().lower() for item in hubs.split(",") if item.strip()]
    if not requested or requested == ["auto"]:
        return list(AUDIT_REGISTRY.values())
    selected: list[AuditModule] = []
    unknown: list[str] = []
    for hub in requested:
        module = AUDIT_REGISTRY.get(hub)
        if module:
            selected.append(module)
        else:
            unknown.append(hub)
    if unknown:
        selected.append(
            AuditModule(
                hub="unknown",
                endpoints=(),
                fallback=f"Unknown requested hub(s): {', '.join(sorted(unknown))}",
            )
        )
    return selected


def registry_snapshot(modules: list[AuditModule]) -> dict[str, dict[str, object]]:
    return {
        module.hub: {
            "object_types": list(module.object_types),
            "required_scopes": list(module.required_scopes),
            "endpoints": list(module.endpoints),
            "quality_checks": list(module.quality_checks),
            "fallback": module.fallback,
        }
        for module in modules
    }
