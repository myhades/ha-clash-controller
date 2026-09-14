"""Backward-compatible imports for the internal API client package."""

try:
    from .clash_api import (
        APITimeoutError,
        APIAuthError,
        APIClientError,
        APIConnectionError,
        ClashAPI,
        ClashAPIError,
        EndpointCapability,
        CapabilityReport,
        FetchResult,
        VersionInfo,
    )
except ImportError:  # Support direct file loading by compatibility tooling.
    from custom_components.clash_controller.clash_api import (
        APITimeoutError,
        APIAuthError,
        APIClientError,
        APIConnectionError,
        ClashAPI,
        ClashAPIError,
        EndpointCapability,
        CapabilityReport,
        FetchResult,
        VersionInfo,
    )

__all__ = (
    "APITimeoutError",
    "APIAuthError",
    "APIClientError",
    "APIConnectionError",
    "ClashAPI",
    "ClashAPIError",
    "EndpointCapability",
    "CapabilityReport",
    "FetchResult",
    "VersionInfo",
)
