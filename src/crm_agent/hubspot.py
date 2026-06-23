from __future__ import annotations

import time
from typing import Any

import httpx

from crm_agent.constants import READ_ONLY_METHODS, READ_ONLY_POST_PATH_SUFFIXES
from crm_agent.errors import HubSpotApiError
from crm_agent.io import redact, utc_now_iso
from crm_agent.models import (
    ManifestOperation,
    PortalCapabilities,
    PortalObjectCapabilities,
)
from crm_agent.settings import Settings


class HubSpotConnector:
    """Thin boundary around HubSpot APIs.

    V1 is intentionally explicit: no generic "execute arbitrary endpoint" method
    is exposed outside this class. Apply paths map to known idempotent operations.
    """

    def __init__(self, settings: Settings, *, client: httpx.Client | None = None):
        self.settings = settings
        self.api_version = settings.hubspot_api_version
        self.client = client or httpx.Client(
            base_url=settings.hubspot_base_url,
            timeout=settings.timeout_seconds,
            headers={
                "Authorization": f"Bearer {settings.hubspot_private_app_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        self.client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> dict[str, Any]:
        attempts = self.settings.max_retries + 1
        last_error: HubSpotApiError | None = None
        for attempt in range(attempts):
            response = self.client.request(method, path, json=json_body, params=params)
            if response.status_code == 429 and attempt < attempts - 1:
                retry_after = float(response.headers.get("Retry-After", "1"))
                time.sleep(min(retry_after, 5))
                continue
            if response.status_code == 404 and allow_not_found:
                return {}
            if response.status_code >= 400:
                try:
                    payload = response.json()
                except ValueError:
                    payload = {"message": response.text}
                last_error = HubSpotApiError(
                    f"HubSpot API {method} {path} failed with {response.status_code}: "
                    f"{redact(payload)}",
                    status_code=response.status_code,
                    response=payload,
                )
                break
            if not response.content:
                return {}
            return response.json()
        if last_error:
            raise last_error
        raise HubSpotApiError(f"HubSpot API {method} {path} failed after retries")

    def _read_only_request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> dict[str, Any]:
        method = method.upper()
        read_only_post = method == "POST" and any(
            path.endswith(suffix) for suffix in READ_ONLY_POST_PATH_SUFFIXES
        )
        if method not in READ_ONLY_METHODS and not read_only_post:
            raise HubSpotApiError(f"Audit read-only guard blocked {method} {path}")
        return self._request(
            method,
            path,
            json_body=json_body,
            params=params,
            allow_not_found=allow_not_found,
        )

    def preflight(self) -> PortalCapabilities:
        warnings: list[str] = []
        account: dict[str, Any] = {}
        rate_limits: dict[str, Any] = {}

        try:
            account = self._request("GET", "/account-info/v3/details", allow_not_found=True)
        except HubSpotApiError as error:
            warnings.append(str(error))

        try:
            rate_limits = self._request("GET", "/integrations/v1/limit/daily", allow_not_found=True)
        except HubSpotApiError as error:
            warnings.append(str(error))

        objects: dict[str, PortalObjectCapabilities] = {}
        for object_type in ["companies", "contacts", "deals"]:
            objects[object_type] = self._discover_object(object_type)

        return PortalCapabilities(
            generated_at=utc_now_iso(),
            api_version=self.api_version,
            account=account,
            rate_limits=rate_limits,
            objects=objects,
            warnings=warnings,
        )

    def _discover_object(self, object_type: str) -> PortalObjectCapabilities:
        errors: list[str] = []
        properties: dict[str, dict[str, Any]] = {}
        pipelines: list[dict[str, Any]] = []
        readable = False
        writable = False

        try:
            prop_response = self.get_properties(object_type)
            for item in prop_response.get("results", []):
                if name := item.get("name"):
                    properties[name] = item
            readable = True
            writable = True
        except HubSpotApiError as error:
            errors.append(str(error))

        if object_type == "deals":
            try:
                pipelines = self.get_pipelines(object_type)
            except HubSpotApiError as error:
                errors.append(str(error))

        return PortalObjectCapabilities(
            object_type=object_type,
            readable=readable,
            writable=writable,
            property_count=len(properties),
            properties=properties,
            pipelines=pipelines,
            errors=errors,
        )

    def get_properties(self, object_type: str) -> dict[str, Any]:
        return self._read_only_request(
            "GET",
            f"/crm/properties/{self.api_version}/{object_type}",
        )

    def get_property_groups(self, object_type: str) -> list[dict[str, Any]]:
        return self._read_only_request(
            "GET",
            f"/crm/properties/{self.api_version}/{object_type}/groups",
            allow_not_found=True,
        ).get("results", [])

    def get_property(self, object_type: str, property_name: str) -> dict[str, Any]:
        return self._read_only_request(
            "GET",
            f"/crm/properties/{self.api_version}/{object_type}/{property_name}",
            allow_not_found=True,
        )

    def get_pipelines(self, object_type: str = "deals") -> list[dict[str, Any]]:
        return self._read_only_request(
            "GET",
            f"/crm/pipelines/{self.api_version}/{object_type}",
            allow_not_found=True,
        ).get("results", [])

    def get_association_labels(
        self, from_object_type: str, to_object_type: str
    ) -> list[dict[str, Any]]:
        return self._read_only_request(
            "GET",
            (f"/crm/associations/{self.api_version}/{from_object_type}/{to_object_type}/labels"),
            allow_not_found=True,
        ).get("results", [])

    def get_object_schemas(self) -> list[dict[str, Any]]:
        return self._read_only_request(
            "GET",
            f"/crm-object-schemas/{self.api_version}/schemas",
            allow_not_found=True,
        ).get("results", [])

    def search_object_sample(
        self,
        object_type: str,
        *,
        properties: list[str],
        limit: int = 25,
    ) -> dict[str, Any]:
        payload = {
            "limit": limit,
            "properties": properties[:100],
        }
        return self._read_only_request(
            "POST",
            f"/crm/objects/{object_type}/search",
            json_body=payload,
            allow_not_found=True,
        )

    def get_metadata_endpoint(self, path: str) -> dict[str, Any]:
        return self._read_only_request("GET", path, allow_not_found=True)

    def apply_operation(self, operation: ManifestOperation) -> dict[str, Any]:
        if operation.action == "ensure_property":
            return self.ensure_property(operation)
        if operation.action == "extend_property_options":
            return self.extend_property_options(operation)
        if operation.action == "ensure_pipeline":
            return self.ensure_pipeline(operation)
        if operation.action == "ensure_pipeline_stage":
            return self.ensure_pipeline_stage(operation)
        raise HubSpotApiError(f"Unsupported apply operation: {operation.action}")

    def ensure_property(self, operation: ManifestOperation) -> dict[str, Any]:
        name = operation.payload["name"]
        existing = self.get_property(operation.object_type, name)
        if existing:
            return {"status": "noop", "reason": "property already exists", "result": existing}
        result = self._request(
            "POST",
            f"/crm/properties/{self.api_version}/{operation.object_type}",
            json_body=operation.payload,
        )
        return {"status": "applied", "result": result}

    def extend_property_options(self, operation: ManifestOperation) -> dict[str, Any]:
        name = operation.payload["name"]
        options_to_add = operation.payload.get("options_to_add", [])
        existing = self.get_property(operation.object_type, name)
        if not existing:
            raise HubSpotApiError(f"Property not found for option extension: {name}")
        existing_values = {
            str(item.get("value"))
            for item in existing.get("options", [])
            if item.get("value") is not None
        }
        new_options = [
            item
            for item in options_to_add
            if item.get("value") is not None and str(item.get("value")) not in existing_values
        ]
        if not new_options:
            return {
                "status": "noop",
                "reason": "all enum options already exist",
                "result": existing,
            }
        updated_options = [*existing.get("options", []), *new_options]
        result = self._request(
            "PATCH",
            f"/crm/properties/{self.api_version}/{operation.object_type}/{name}",
            json_body={"options": updated_options},
        )
        return {"status": "applied", "result": result}

    def ensure_pipeline(self, operation: ManifestOperation) -> dict[str, Any]:
        label = operation.payload["label"]
        existing = self._find_pipeline_by_label(operation.object_type, label)
        if existing:
            return {"status": "noop", "reason": "pipeline already exists", "result": existing}
        result = self._request(
            "POST",
            f"/crm/pipelines/{self.api_version}/{operation.object_type}",
            json_body=operation.payload,
        )
        return {"status": "applied", "result": result}

    def ensure_pipeline_stage(self, operation: ManifestOperation) -> dict[str, Any]:
        pipeline_label = operation.expected.get("pipeline_label")
        pipeline = self._find_pipeline_by_label(operation.object_type, pipeline_label)
        if not pipeline:
            raise HubSpotApiError(f"Pipeline not found for stage operation: {pipeline_label}")
        stage_label = operation.payload["label"].lower().strip()
        for stage in pipeline.get("stages", []):
            if stage.get("label", "").lower().strip() == stage_label:
                return {"status": "noop", "reason": "stage already exists", "result": stage}
        result = self._request(
            "POST",
            f"/crm/pipelines/{self.api_version}/{operation.object_type}/{pipeline['id']}/stages",
            json_body=operation.payload,
        )
        return {"status": "applied", "result": result}

    def _find_pipeline_by_label(self, object_type: str, label: str | None) -> dict[str, Any] | None:
        if not label:
            return None
        for pipeline in self.get_pipelines(object_type):
            if pipeline.get("label", "").lower().strip() == label.lower().strip():
                return pipeline
        return None
