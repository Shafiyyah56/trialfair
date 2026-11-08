"""SQLite persistence with per-operation connections and no import-time writes.

Only validated outputs are saved. Uploaded narratives are removed before disk
persistence; runtime .trialfair contents remain ignored by Git. Local research
outputs can still be sensitive and belong under the human team's access controls.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from app.contracts import RunResult
from app.validation import validate_run


class RunStore(Protocol):
    def save(self, result: RunResult) -> None: ...

    def get(self, run_id: str) -> RunResult | None: ...


def _without_narratives(result: RunResult) -> RunResult:
    safe = result.model_copy(deep=True)
    if safe.screening:
        safe.screening.trial_bundle.narrative_entries = []
        safe.screening.symptom_mappings = []
    if safe.planner_input:
        safe.planner_input.screening.trial_bundle.narrative_entries = []
        safe.planner_input.screening.symptom_mappings = []
    return safe


class SQLiteRunStore:
    """Parameterised SQL and bounded connections support concurrent local requests."""

    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS runs "
                    "(run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
                )
                yield connection
        finally:
            connection.close()

    def save(self, result: RunResult) -> None:
        validate_run(result)
        safe = _without_narratives(result)
        validate_run(safe)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO runs (run_id, payload) VALUES (?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET payload=excluded.payload",
                (safe.run_id, safe.model_dump_json()),
            )

    def get(self, run_id: str) -> RunResult | None:
        if not self.path.exists():
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        result = RunResult.model_validate_json(row[0])
        validate_run(result)
        return result
