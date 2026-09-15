"""Clash-compatible controller API client."""

from .capabilities import CapabilityReport, EndpointCapability
from .client import ClashAPI
from .exceptions import (
    APIAuthError,
    APIClientError,
    APIConnectionError,
    APITimeoutError,
    ClashAPIError,
)
from .models import FetchResult, VersionInfo

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
