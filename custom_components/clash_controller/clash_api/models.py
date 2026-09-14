"""Response models for Clash-compatible controller APIs."""

from collections.abc import Iterator, Mapping
from typing import Any

from .exceptions import ClashAPIError


class FetchResult(Mapping[str, Any]):
    """Data and endpoint failures collected during one polling cycle."""

    __slots__ = ("data", "errors")

    def __init__(
        self,
        data: dict[str, Any],
        errors: dict[str, ClashAPIError],
    ) -> None:
        self.data = data
        self.errors = errors

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)
