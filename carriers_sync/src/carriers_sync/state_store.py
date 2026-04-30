"""Persists last successful ProviderResult per account and the set of
currently-published discovery entities. Used to repopulate sensors after
container restart and to clean up entities for removed accounts.

Storage is a single JSON file at /data/state.json. Writes are atomic
(temp file + os.replace). On corruption, the file is moved aside and
fresh state is returned.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from carriers_sync.providers.base import LineUsage, ProviderResult

logger = logging.getLogger("carriers_sync.state")


@dataclass
class State:
    last_results: dict[str, ProviderResult] = field(default_factory=dict)
    last_published_entities: set[str] = field(default_factory=set)


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> State:
        if not self.path.exists():
            return State()
        try:
            raw = json.loads(self.path.read_text())
        except json.JSONDecodeError as e:
            logger.warning("state.json is corrupt (%s); starting fresh", e)
            self._move_aside_corrupt()
            return State()

        results: dict[str, ProviderResult] = {}
        for acct_id, payload in raw.get("last_results", {}).items():
            try:
                results[acct_id] = _result_from_dict(payload)
            except (KeyError, TypeError, ValueError) as e:
                logger.warning("dropping corrupt account %s from state: %s", acct_id, e)

        return State(
            last_results=results,
            last_published_entities=set(raw.get("last_published_entities", [])),
        )

    def save(self, state: State) -> None:
        payload = {
            "last_results": {
                acct: _result_to_dict(res) for acct, res in state.last_results.items()
            },
            "last_published_entities": sorted(state.last_published_entities),
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        os.replace(tmp, self.path)

    def _move_aside_corrupt(self) -> None:
        if not self.path.exists():
            return
        backup = self.path.with_suffix(self.path.suffix + ".corrupt")
        try:
            os.replace(self.path, backup)
        except OSError:
            self.path.unlink(missing_ok=True)


def _result_to_dict(r: ProviderResult) -> dict[str, Any]:
    return {
        "account_id": r.account_id,
        "fetched_at": r.fetched_at.isoformat(),
        "lines": [
            {
                "line_id": line.line_id,
                "label": line.label,
                "consumed_gb": line.consumed_gb,
                "quota_gb": line.quota_gb,
                "extra_consumed_gb": line.extra_consumed_gb,
                "is_secondary": line.is_secondary,
                "parent_line_id": line.parent_line_id,
            }
            for line in r.lines
        ],
    }


def _result_from_dict(d: dict[str, Any]) -> ProviderResult:
    return ProviderResult(
        account_id=d["account_id"],
        fetched_at=datetime.fromisoformat(d["fetched_at"]),
        lines=[
            LineUsage(
                line_id=line["line_id"],
                label=line["label"],
                consumed_gb=float(line["consumed_gb"]),
                quota_gb=None if line["quota_gb"] is None else float(line["quota_gb"]),
                extra_consumed_gb=float(line["extra_consumed_gb"]),
                is_secondary=bool(line["is_secondary"]),
                parent_line_id=line["parent_line_id"],
            )
            for line in d["lines"]
        ],
    )
