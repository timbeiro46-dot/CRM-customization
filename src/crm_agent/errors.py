from __future__ import annotations


class CrmAgentError(Exception):
    """Base error for user-facing CLI failures."""


class ConfigurationError(CrmAgentError):
    """Raised when local environment configuration is missing or invalid."""


class CapabilityError(CrmAgentError):
    """Raised when a manifest depends on unsupported portal capabilities."""


class ManifestValidationError(CrmAgentError):
    """Raised when a manifest is unsafe or internally inconsistent."""


class ApprovalError(CrmAgentError):
    """Raised when an apply attempt lacks a matching approval."""


class HubSpotApiError(CrmAgentError):
    """Raised for non-retryable HubSpot API errors."""

    def __init__(self, message: str, *, status_code: int | None = None, response: object = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response
