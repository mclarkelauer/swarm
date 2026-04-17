"""Agent A/B testing — experiment management for variant comparison."""

from __future__ import annotations

import random
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def init_experiments_db(path: Path) -> sqlite3.Connection:
    """Create or open the experiments database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS experiments (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL UNIQUE,
            agent_a     TEXT NOT NULL,
            agent_b     TEXT NOT NULL,
            traffic_pct REAL NOT NULL DEFAULT 50.0,
            status      TEXT NOT NULL DEFAULT 'active',
            created_at  TEXT NOT NULL DEFAULT '',
            ended_at    TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS experiment_results (
            id            TEXT PRIMARY KEY,
            experiment_id TEXT NOT NULL,
            variant       TEXT NOT NULL,
            run_id        TEXT NOT NULL DEFAULT '',
            step_id       TEXT NOT NULL DEFAULT '',
            success       INTEGER NOT NULL DEFAULT 1,
            duration_secs REAL NOT NULL DEFAULT 0.0,
            tokens_used   INTEGER NOT NULL DEFAULT 0,
            cost_usd      REAL NOT NULL DEFAULT 0.0,
            recorded_at   TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (experiment_id) REFERENCES experiments(id)
        )
        """
    )
    conn.commit()
    return conn


class ExperimentAPI:
    """A/B testing for agent variants.

    Creates experiments that compare two agent variants. During
    execution, the experiment routes to variant A or B based on
    the configured traffic split.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: Path) -> None:
        self._conn = init_experiments_db(db_path)

    def create(
        self,
        name: str,
        agent_a: str,
        agent_b: str,
        traffic_pct: float = 50.0,
        description: str = "",
    ) -> dict[str, Any]:
        """Create a new A/B experiment.

        Args:
            name: Unique experiment name.
            agent_a: Agent name/ID for variant A (control).
            agent_b: Agent name/ID for variant B (treatment).
            traffic_pct: Percentage of traffic routed to variant B
                (0-100). Default 50 = even split.
            description: Human-readable description.

        Returns:
            Dict with the created experiment.
        """
        exp_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC).isoformat()

        self._conn.execute(
            "INSERT INTO experiments (id, name, agent_a, agent_b, "
            "traffic_pct, status, created_at, description) "
            "VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
            (exp_id, name, agent_a, agent_b, traffic_pct, now, description),
        )
        self._conn.commit()

        return {
            "id": exp_id,
            "name": name,
            "agent_a": agent_a,
            "agent_b": agent_b,
            "traffic_pct": traffic_pct,
            "status": "active",
            "created_at": now,
            "description": description,
        }

    def resolve_variant(self, experiment_name: str) -> tuple[str, str]:
        """Resolve which variant to use for this invocation.

        Uses the traffic_pct to randomly select variant A or B.

        Args:
            experiment_name: The experiment name.

        Returns:
            Tuple of (agent_name, variant_label) where variant_label
            is 'A' or 'B'.

        Raises:
            ValueError: If experiment not found or not active.
        """
        cur = self._conn.execute(
            "SELECT agent_a, agent_b, traffic_pct, status "
            "FROM experiments WHERE name = ?",
            (experiment_name,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Experiment '{experiment_name}' not found")
        if row[3] != "active":
            raise ValueError(f"Experiment '{experiment_name}' is {row[3]}")

        agent_a, agent_b, traffic_pct = row[0], row[1], row[2]

        # Route based on traffic percentage (traffic_pct = % to B)
        if random.random() * 100 < traffic_pct:  # noqa: S311
            return agent_b, "B"
        return agent_a, "A"

    def record_result(
        self,
        experiment_name: str,
        variant: str,
        *,
        success: bool = True,
        duration_secs: float = 0.0,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
        run_id: str = "",
        step_id: str = "",
    ) -> dict[str, Any]:
        """Record a result for an experiment variant.

        Args:
            experiment_name: The experiment name.
            variant: 'A' or 'B'.
            success: Whether the run was successful.
            duration_secs: Step duration.
            tokens_used: Tokens consumed.
            cost_usd: Cost in USD.
            run_id: Plan run identifier.
            step_id: Step identifier.

        Returns:
            Dict with the recorded result.
        """
        cur = self._conn.execute(
            "SELECT id FROM experiments WHERE name = ?",
            (experiment_name,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Experiment '{experiment_name}' not found")

        exp_id = row[0]
        result_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC).isoformat()

        self._conn.execute(
            "INSERT INTO experiment_results (id, experiment_id, variant, "
            "run_id, step_id, success, duration_secs, tokens_used, "
            "cost_usd, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                result_id, exp_id, variant, run_id, step_id,
                1 if success else 0, duration_secs, tokens_used,
                cost_usd, now,
            ),
        )
        self._conn.commit()

        return {
            "id": result_id,
            "experiment_id": exp_id,
            "variant": variant,
            "success": success,
        }

    def get_results(self, experiment_name: str) -> dict[str, Any]:
        """Get aggregated results for an experiment.

        Returns:
            Dict with per-variant aggregated statistics.
        """
        cur = self._conn.execute(
            "SELECT id, agent_a, agent_b, traffic_pct, status, description "
            "FROM experiments WHERE name = ?",
            (experiment_name,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Experiment '{experiment_name}' not found")

        exp_id = row[0]

        variants: dict[str, dict[str, Any]] = {}
        for variant_label, agent_name in [("A", row[1]), ("B", row[2])]:
            vcur = self._conn.execute(
                "SELECT COUNT(*), SUM(success), SUM(duration_secs), "
                "SUM(tokens_used), SUM(cost_usd) "
                "FROM experiment_results "
                "WHERE experiment_id = ? AND variant = ?",
                (exp_id, variant_label),
            )
            vrow = vcur.fetchone()
            total = vrow[0] or 0
            successes = vrow[1] or 0
            variants[variant_label] = {
                "agent": agent_name,
                "total_runs": total,
                "successes": successes,
                "failures": total - successes,
                "success_rate": successes / total if total > 0 else 0.0,
                "total_duration_secs": vrow[2] or 0.0,
                "avg_duration_secs": (vrow[2] or 0.0) / total if total > 0 else 0.0,
                "total_tokens": vrow[3] or 0,
                "total_cost_usd": vrow[4] or 0.0,
            }

        # Determine winner (higher success rate wins)
        winner = None
        a_rate = variants["A"]["success_rate"]
        b_rate = variants["B"]["success_rate"]
        if variants["A"]["total_runs"] > 0 and variants["B"]["total_runs"] > 0:
            if a_rate > b_rate:
                winner = "A"
            elif b_rate > a_rate:
                winner = "B"
            else:
                winner = "tie"

        return {
            "name": experiment_name,
            "status": row[4],
            "description": row[5],
            "variants": variants,
            "winner": winner,
        }

    def end_experiment(self, experiment_name: str) -> bool:
        """End an active experiment.

        Returns:
            True if the experiment was found and ended.
        """
        now = datetime.now(tz=UTC).isoformat()
        cur = self._conn.execute(
            "UPDATE experiments SET status = 'ended', ended_at = ? "
            "WHERE name = ? AND status = 'active'",
            (now, experiment_name),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def list_experiments(self, status: str = "") -> list[dict[str, Any]]:
        """List experiments, optionally filtered by status.

        Returns:
            List of experiment summary dicts.
        """
        if status:
            cur = self._conn.execute(
                "SELECT id, name, agent_a, agent_b, traffic_pct, status, "
                "created_at, description FROM experiments WHERE status = ? "
                "ORDER BY created_at DESC",
                (status,),
            )
        else:
            cur = self._conn.execute(
                "SELECT id, name, agent_a, agent_b, traffic_pct, status, "
                "created_at, description FROM experiments "
                "ORDER BY created_at DESC"
            )
        return [
            {
                "id": row[0],
                "name": row[1],
                "agent_a": row[2],
                "agent_b": row[3],
                "traffic_pct": row[4],
                "status": row[5],
                "created_at": row[6],
                "description": row[7],
            }
            for row in cur.fetchall()
        ]

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    def __enter__(self) -> ExperimentAPI:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
