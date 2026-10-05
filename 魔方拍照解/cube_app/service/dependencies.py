"""Live dependency view preserving existing facade replacement behavior."""

from __future__ import annotations

from typing import Any, Mapping


class Dependencies:
    def __init__(self, namespace: Mapping[str, Any]):
        self._namespace = namespace

    def __getattr__(self, name: str) -> Any:
        try:
            return self._namespace[name]
        except KeyError as exc:
            raise AttributeError(name) from exc
