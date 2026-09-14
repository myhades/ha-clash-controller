"""Clash-compatible controller API client."""

from .capabilities import EndpointCapability
from .client import ClashAPI
from .exceptions import (
    APITimeoutError,
    APIAuthError,
    APIClientError,
    APIConnectionError,
    ClashAPIError,
)
from .models import FetchResult

__all__ = (
    "APITimeoutError",
    "APIAuthError",
    "APIClientError",
    "APIConnectionError",
    "ClashAPI",
    "ClashAPIError",
    "EndpointCapability",
    "FetchResult",
)
