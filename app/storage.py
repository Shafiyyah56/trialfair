"""Agent 2 owns SQLite persistence; no files are created by importing this module."""

from typing import Protocol

from app.contracts import RunResult


class RunStore(Protocol):
    def save(self, result: RunResult) -> None: ...

    def get(self, run_id: str) -> RunResult | None: ...
