"""Response models for Clash-compatible controller APIs."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from .exceptions import ClashAPIError


@dataclass(frozen=True, slots=True, eq=False)
class VersionInfo(Mapping[str, str]):
    """Normalized version fields, with legacy mapping access."""

    model: str
    version: str
    meta: str

    def __getitem__(self, key: str) -> str:
        if key == "model":
            return self.model
        if key == "version":
            return self.version
        if key == "meta":
            return self.meta
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(("meta", "model", "version"))

    def __len__(self) -> int:
        return 3


class FetchResult(Mapping[str, Any]):
    """Data and endpoint failures collected during one polling cycle."""

    __slots__ = ("data", "errors")

    data: dict[str, Any]
    errors: dict[str, ClashAPIError]

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
