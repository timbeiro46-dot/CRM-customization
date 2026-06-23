from __future__ import annotations

from pathlib import Path

from crm_agent.io import slugify
from crm_agent.models import BusinessContext


def build_business_context(
    *,
    project_slug: str,
    business_name: str,
    industry: str | None = None,
    sales_motion: str | None = None,
    inputs: list[Path] | None = None,
) -> BusinessContext:
    source_documents: list[str] = []
    raw_chunks: list[str] = []
    for path in inputs or []:
        source_documents.append(str(path))
        raw_chunks.append(f"# Source: {path}\n{path.read_text(encoding='utf-8')}")

    return BusinessContext(
        project_slug=slugify(project_slug),
        business_name=business_name,
        industry=industry,
        sales_motion=sales_motion,
        sales_process_notes=(
            "Replace this with the user's sales process. Include entry criteria, exit criteria, "
            "required handoffs, and what must be visible on company/contact/deal records."
        ),
        data_requirements=[
            {
                "object_type": "companies",
                "field_name": "segment",
                "label": "Segment",
                "type": "enumeration",
                "field_type": "select",
                "options": ["SMB", "Mid Market", "Enterprise"],
                "reason": "Example placeholder; edit before planning.",
            },
            {
                "object_type": "deals",
                "field_name": "qualification_notes",
                "label": "Qualification Notes",
                "type": "string",
                "field_type": "textarea",
                "reason": "Example placeholder; edit before planning.",
            },
        ],
        reporting_goals=[
            "Pipeline health by stage",
            "Open opportunities by owner",
            "Closed-won/lost trends",
        ],
        source_documents=source_documents,
        raw_notes="\n\n".join(raw_chunks),
    )
