"""Exceptions raised by the Clash-compatible API client."""


class ClashAPIError(Exception):
    """Base exception for Clash API failures."""


class APIAuthError(ClashAPIError):
    """Exception class for auth error."""


class APIClientError(ClashAPIError):
    """Exception class for generic client error."""


class APIConnectionError(ClashAPIError):
    """Exception class for connection error."""


class APITimeoutError(APIConnectionError):
    """Exception class for timeout error."""
