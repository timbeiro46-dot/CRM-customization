from __future__ import annotations

from pydantic import ValidationError

from crm_agent.models import ManifestOperation, PropertySpec


def test_delete_operations_are_rejected_by_model() -> None:
    try:
        ManifestOperation(
            id="delete:companies:bad",
            action="ensure_property",
            object_type="companies",
            method="DELETE",
            endpoint="/crm/properties/2026-03/companies/bad",
            rollback="Not allowed.",
        )
    except ValidationError as error:
        assert "DELETE operations are blocked" in str(error)
    else:
        raise AssertionError("Expected DELETE operation to fail validation")


def test_select_property_requires_options() -> None:
    try:
        PropertySpec(
            object_type="companies",
            name="acme_segment",
            label="Segment",
            group_name="companyinformation",
            type="enumeration",
            field_type="select",
        )
    except ValidationError as error:
        assert "needs options" in str(error)
    else:
        raise AssertionError("Expected select property without options to fail")
