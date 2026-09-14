"""Capability models for Clash-compatible controller APIs."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from .exceptions import ClashAPIError


class EndpointCapability:
    """Result of probing one API transport endpoint."""

    __slots__ = ("error", "status_code", "supported")

    supported: bool
    error: ClashAPIError | None
    status_code: int | None

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


@dataclass(frozen=True, slots=True, eq=False)
class CapabilityReport(Mapping[str, bool]):
    """Effective capabilities and the latest probe outcomes.

    used_cached is true for cache hits and failed probes retaining prior capabilities.
    Mapping access reads the effective capability flags for existing callers.
    """

    capabilities: dict[str, bool]
    outcomes: dict[str, EndpointCapability]
    used_cached: bool = False

    def __getitem__(self, key: str) -> bool:
        return self.capabilities[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.capabilities)

    def __len__(self) -> int:
        return len(self.capabilities)
