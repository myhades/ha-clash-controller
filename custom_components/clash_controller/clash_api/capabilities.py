"""Capability models for Clash-compatible controller APIs."""

from .exceptions import ClashAPIError


class EndpointCapability:
    """Result of probing one API transport endpoint."""

    __slots__ = ("error", "status_code", "supported")

    def __init__(
        self,
        supported: bool,
        *,
        error: ClashAPIError | None = None,
        status_code: int | None = None,
    ) -> None:
        self.supported = supported
        self.error = error
        self.status_code = status_code
