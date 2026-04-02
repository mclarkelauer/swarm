# Advanced Orchestration Features: Design Document

Two features that extend the Swarm plan executor with runtime adaptability
and structured inter-agent communication.

---

## 1. Dynamic Replanning

### Motivation

The current executor runs a plan DAG to completion, but it cannot adapt to
unexpected step outputs.  A step might produce partial results, hit an error
that requires a remediation workflow, or emit output that should fork the plan
down a different branch.  Dynamic replanning lets plans react to runtime
observations without human intervention.

### 1.1 New Condition Type: `output_contains:<step_id>:<pattern>`

Evaluates a regex pattern against the stdout log file of a completed step.
The output file is located at `<artifacts_dir>/<step_id>.stdout.log` (the
convention already used by `launch_agent` to capture subprocess output).

#### Changes to `src/swarm/plan/conditions.py`

```python
# Add to _KNOWN_PREFIXES
_KNOWN_PREFIXES = (
    "artifact_exists:",
    "step_completed:",
    "step_failed:",
    "iteration_ge:",
    "output_contains:",         # NEW
)
```

**Validation** (`validate_condition`):

```python
if prefix == "output_contains:":
    # Format: output_contains:<step_id>:<regex_pattern>
    parts = value.split(":", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return (
            f"Condition '{condition}': output_contains requires format "
            f"'output_contains:<step_id>:<regex_pattern>'"
        )
    # Validate that the regex compiles
    try:
        re.compile(parts[1])
    except re.error as exc:
        return (
            f"Condition '{condition}': invalid regex pattern: {exc}"
        )
    return None
```

**Evaluation** (`evaluate_condition`):

```python
if condition.startswith("output_contains:"):
    rest = condition[len("output_contains:"):]
    parts = rest.split(":", 1)
    if len(parts) != 2:
        return False
    step_id, pattern = parts
    if artifacts_dir is None:
        return True  # permissive fallback
    log_path = artifacts_dir / f"{step_id}.stdout.log"
    if not log_path.exists():
        return False
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return re.search(pattern, content) is not None
```

This requires adding `import re` at the top of `conditions.py`.

**Key decisions**:
- The regex is applied with `re.search` (match anywhere, not anchored).
- The full stdout log is read into memory.  This is acceptable because
  stdout logs are typically small (< 1 MB for a Claude CLI session).
- On missing or unreadable log files, the condition evaluates to `False`
  (safe default -- the gated step does not fire).
- The `artifacts_dir` permissive fallback (`None` -> `True`) is consistent
  with `artifact_exists:`.

### 1.2 New Step Type: `decision`

A `decision` step is a lightweight branching node that evaluates a list of
conditional actions and activates or skips downstream steps without launching
any subprocess.  It runs entirely inside the executor.

#### Data Model

```python
# src/swarm/plan/models.py

@dataclass(frozen=True)
class ConditionalAction:
    """A single branch in a decision step."""

    condition: str                       # condition expression (same syntax as step.condition)
    activate_steps: tuple[str, ...] = () # step IDs to mark as eligible
    skip_steps: tuple[str, ...] = ()     # step IDs to mark as skipped

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"condition": self.condition}
        if self.activate_steps:
            d["activate_steps"] = list(self.activate_steps)
        if self.skip_steps:
            d["skip_steps"] = list(self.skip_steps)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ConditionalAction:
        return cls(
            condition=d.get("condition", ""),
            activate_steps=tuple(d.get("activate_steps", [])),
            skip_steps=tuple(d.get("skip_steps", [])),
        )


@dataclass(frozen=True)
class DecisionConfig:
    """Configuration for a decision step."""

    actions: tuple[ConditionalAction, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"actions": [a.to_dict() for a in self.actions]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DecisionConfig:
        return cls(
            actions=tuple(ConditionalAction.from_dict(a) for a in d.get("actions", []))
        )
```

#### PlanStep Changes

```python
# Add to PlanStep fields:
decision_config: DecisionConfig | None = None

# Add to PlanStep.to_dict():
if self.decision_config is not None:
    d["decision_config"] = self.decision_config.to_dict()

# Add to PlanStep.from_dict():
decision_config = None
if "decision_config" in d:
    decision_config = DecisionConfig.from_dict(d["decision_config"])
```

#### Parser Validation (`src/swarm/plan/parser.py`)

```python
# Add "decision" to valid step types
_VALID_STEP_TYPES = {"task", "checkpoint", "loop", "fan_out", "join", "decision"}

# Add validation block in validate_plan():
if step.type == "decision":
    if step.decision_config is None:
        errors.append(f"Decision step '{step.id}' must have decision_config")
    else:
        if not step.decision_config.actions:
            errors.append(
                f"Decision step '{step.id}' must have at least one action"
            )
        for i, action in enumerate(step.decision_config.actions):
            cond_err = validate_condition(action.condition)
            if cond_err is not None:
                errors.append(
                    f"Decision step '{step.id}' action {i}: {cond_err}"
                )
            for sid in action.activate_steps:
                if sid not in step_ids:
                    errors.append(
                        f"Decision step '{step.id}' action {i}: "
                        f"activate_steps references unknown step '{sid}'"
                    )
            for sid in action.skip_steps:
                if sid not in step_ids:
                    errors.append(
                        f"Decision step '{step.id}' action {i}: "
                        f"skip_steps references unknown step '{sid}'"
                    )
```

Decision steps do not need `agent_type` or `prompt` (though `prompt` serves
as a human-readable description of the branching logic).

#### Executor Integration (`src/swarm/plan/executor.py`)

```python
def handle_decision(run_state: RunState, step: PlanStep) -> None:
    """Evaluate decision conditions and activate/skip downstream steps."""
    if step.decision_config is None:
        record_failure(
            run_state, step, attempt=0,
            message="Decision step missing decision_config",
        )
        return

    activated: list[str] = []
    skipped: list[str] = []

    for action in step.decision_config.actions:
        if evaluate_condition(
            action.condition,
            run_state.completed,
            step_outcomes=run_state.step_outcomes,
            artifacts_dir=run_state.artifacts_dir,
        ):
            activated.extend(action.activate_steps)
            for skip_id in action.skip_steps:
                skip_step = _find_step(run_state.plan, skip_id)
                record_skip(
                    run_state, skip_step, attempt=0,
                    message=f"Skipped by decision step '{step.id}'",
                )
                skipped.append(skip_id)

    record_success(
        run_state, step, attempt=0,
        message=f"Activated: {activated}, Skipped: {skipped}",
    )
```

Add to the main dispatch in `execute_plan`:

```python
elif step.type == "decision":
    handle_decision(run_state, step)
```

**How activation works**: Steps listed in `activate_steps` are not force-run;
they simply become eligible.  Their own `depends_on` and `condition` still
apply.  Steps in `skip_steps` are immediately marked as "skipped" and will
not execute.  This is a one-way gate -- once skipped, a step stays skipped.

### 1.3 Self-Modifying Plans via `plan_replan`

#### `max_replans` Field on Plan

```python
# src/swarm/plan/models.py  (Plan class)

@dataclass
class Plan:
    version: int
    goal: str
    steps: list[PlanStep]
    variables: dict[str, str] = field(default_factory=dict)
    max_replans: int = 5  # NEW: safety limit
```

Serialization in `to_dict` / `from_dict`:

```python
# to_dict:
if self.max_replans != 5:
    d["max_replans"] = self.max_replans

# from_dict:
max_replans=d.get("max_replans", 5),
```

#### `replan_count` Field on RunLog

```python
# src/swarm/plan/run_log.py  (RunLog class)
replan_count: int = 0

# to_dict:
if self.replan_count > 0:
    d["replan_count"] = self.replan_count

# from_dict:
replan_count=d.get("replan_count", 0),
```

#### `replan_count` Field on RunState

```python
# src/swarm/plan/executor.py  (RunState class)
replan_count: int = 0
```

Reconstructed from `run_state.log.replan_count` in `init_run_state`.

#### MCP Tool: `plan_replan`

```python
# src/swarm/mcp/plan_tools.py

@mcp.tool()
def plan_replan(
    run_log_path: str,
    insert_after: str,
    new_steps_json: str,
) -> str:
    """Insert remediation steps into the active plan during execution.

    A convenience wrapper around ``plan_amend`` that:
    1. Loads the run log to find the active plan path.
    2. Checks the replan safety limit (``max_replans``).
    3. Increments the replan counter in the run log.
    4. Delegates to ``plan_amend`` for the actual insertion.

    Args:
        run_log_path: Path to the active run log JSON file.
        insert_after: ID of the step after which to insert new steps.
        new_steps_json: JSON array of step objects to insert.

    Returns:
        JSON ``{path, version, errors, inserted_steps, replan_count}``
        -- same as ``plan_amend`` plus the updated replan count.
        Returns ``{"error": "..."}`` if the replan limit is exceeded
        or the run log cannot be loaded.
    """
    # 1. Load run log
    try:
        log = load_run_log(Path(run_log_path))
    except FileNotFoundError:
        return json.dumps({"error": f"Run log not found: {run_log_path}"})

    # 2. Load plan to check max_replans
    plan_path = log.plan_path
    if not plan_path:
        return json.dumps({"error": "Run log has no plan_path"})

    try:
        plan = load_plan(Path(plan_path))
    except FileNotFoundError:
        return json.dumps({"error": f"Plan not found: {plan_path}"})

    # 3. Check safety limit
    if log.replan_count >= plan.max_replans:
        return json.dumps({
            "error": (
                f"Replan limit reached ({log.replan_count}/{plan.max_replans}). "
                f"Increase max_replans on the plan to allow more."
            ),
        })

    # 4. Delegate to plan_amend
    result_json = plan_amend(
        plan_path=plan_path,
        insert_after=insert_after,
        new_steps_json=new_steps_json,
    )
    result = json.loads(result_json)

    if result.get("errors"):
        return result_json  # pass through validation errors

    # 5. Increment replan counter and update run log
    log.replan_count += 1
    # Update plan_path to point to the new version
    if result.get("path"):
        log.plan_path = result["path"]
        log.plan_version = result["version"]
    write_run_log(log, Path(run_log_path))

    result["replan_count"] = log.replan_count
    return json.dumps(result)
```

#### Executor Integration for Automatic Replanning

The executor can be extended with an optional replan hook that fires on step
failure.  This is _not_ an LLM call -- it is a deterministic policy defined
in the plan itself.

```python
# New optional PlanStep field:
replan_on_failure: str = ""  # JSON-encoded list of steps to insert on failure

# In execute_foreground, after recording a failure with on_failure="stop":
if step.replan_on_failure and run_state.replan_count < run_state.plan.max_replans:
    new_steps = json.loads(step.replan_on_failure)
    # ... call internal _amend_plan() and reload ...
    run_state.replan_count += 1
    run_state.log.replan_count = run_state.replan_count
```

However, the primary replan path is the MCP tool (`plan_replan`), which
allows Claude (the orchestrating agent) to decide what remediation steps to
insert.  The `replan_on_failure` field is a static fallback for plans that
want deterministic auto-remediation without orchestrator involvement.

### 1.4 Example Usage

#### Example: Build Pipeline with Decision-Based Error Routing

```json
{
  "version": 1,
  "goal": "Build, test, and deploy with error-aware branching",
  "max_replans": 3,
  "steps": [
    {
      "id": "build",
      "type": "task",
      "prompt": "Build the project",
      "agent_type": "builder",
      "output_artifact": "build.log"
    },
    {
      "id": "check-build-output",
      "type": "decision",
      "prompt": "Route based on build output",
      "depends_on": ["build"],
      "decision_config": {
        "actions": [
          {
            "condition": "output_contains:build:ERROR.*dependency",
            "activate_steps": ["fix-deps"],
            "skip_steps": ["test", "deploy"]
          },
          {
            "condition": "output_contains:build:WARNING.*deprecated",
            "activate_steps": ["deprecation-audit"],
            "skip_steps": []
          },
          {
            "condition": "step_completed:build",
            "activate_steps": ["test"],
            "skip_steps": []
          }
        ]
      }
    },
    {
      "id": "fix-deps",
      "type": "task",
      "prompt": "Fix dependency errors found in build",
      "agent_type": "dependency-fixer",
      "depends_on": ["check-build-output"],
      "condition": "never"
    },
    {
      "id": "deprecation-audit",
      "type": "task",
      "prompt": "Audit deprecated API usage",
      "agent_type": "code-reviewer",
      "depends_on": ["check-build-output"],
      "condition": "never"
    },
    {
      "id": "test",
      "type": "task",
      "prompt": "Run the test suite",
      "agent_type": "tester",
      "depends_on": ["check-build-output"]
    },
    {
      "id": "deploy",
      "type": "task",
      "prompt": "Deploy to staging",
      "agent_type": "deployer",
      "depends_on": ["test"]
    }
  ]
}
```

**How it works**: The `fix-deps` and `deprecation-audit` steps start with
`condition: "never"` so they are inert by default.  The `check-build-output`
decision step inspects the build log at runtime:
- If it contains `ERROR.*dependency`, the decision step skips `test` and
  `deploy`, then lets `fix-deps` become eligible (its `condition: "never"`
  would need to be patched to `""` by the decision handler -- see note below).
- If it contains `WARNING.*deprecated`, the deprecation audit is activated
  alongside the normal test flow.
- The third action (fallback) activates `test` for the happy path.

**Activation semantics note**: `activate_steps` does not override a step's
own `condition` field.  Steps intended to be conditionally activated by a
decision step should use `condition: "never"` and have the decision handler
internally override this to `""`.  The handler tracks this in a
`RunState.decision_overrides: dict[str, str]` map, and `get_ready_steps` is
extended to consult it.

#### Example: Mid-Run Replanning via MCP Tool

```
# Claude (orchestrator) observes a failure in step "test":
plan_replan(
    run_log_path="/plans/run_log.json",
    insert_after="test",
    new_steps_json='[{"id":"fix-tests","type":"task","prompt":"Fix failing tests","agent_type":"debugger"}]'
)
# Returns: {"path":"/plans/plan_v3.json","version":3,"errors":[],"inserted_steps":["fix-tests"],"replan_count":1}
```

### 1.5 Testing Strategy

| Test area | Technique |
|---|---|
| `output_contains` validation | Parametrized `test_validate_condition` cases: valid patterns, empty step_id, empty pattern, invalid regex |
| `output_contains` evaluation | `tmp_path` fixture writing fake `.stdout.log` files; assert True/False for matching/non-matching patterns, missing files |
| `DecisionConfig` serde | Round-trip `to_dict` / `from_dict` with multiple actions |
| Decision step validation | Parser tests: missing config, empty actions, unknown step references in activate/skip |
| `handle_decision` | Unit test with a mock `RunState`; verify that `skip_steps` are recorded as skipped, `activate_steps` are noted, decision step itself is marked completed |
| `plan_replan` MCP tool | Integration test: create a plan, write a run log, call `plan_replan`, verify new version saved, replan_count incremented |
| Replan safety limit | Call `plan_replan` when `replan_count >= max_replans`, assert error returned |
| `max_replans` serde | Round-trip `Plan.to_dict` / `from_dict` with non-default values |
| Decision + executor integration | End-to-end test (mocked `launch_agent`) where a decision step skips one branch and activates another, verify the correct steps run |

**Test count estimate**: ~25 new tests across `tests/plan/test_conditions.py`,
`tests/plan/test_models.py`, `tests/plan/test_parser.py`,
`tests/plan/test_executor.py`, and `tests/mcp/test_plan_tools.py`.

---

## 2. Inter-Agent Message Bus

### Motivation

The current plan system uses file artifacts as the sole communication channel
between agents.  This works well for structured outputs (code, reports) but
is clumsy for short-lived signals: "I found 3 critical bugs, focus on module
X", or "authentication token for downstream service is ABC123".

A message bus provides a lightweight, typed, queryable channel for
inter-agent communication that complements (not replaces) file artifacts.

### 2.1 Data Model

```python
# src/swarm/plan/messages.py

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any


_VALID_MESSAGE_TYPES = ("request", "response", "broadcast")


@dataclass(frozen=True)
class AgentMessage:
    """A single message between agents in a plan run."""

    id: str                  # UUID
    from_agent: str          # agent_type of sender
    to_agent: str            # agent_type of receiver ("*" for broadcast)
    step_id: str             # step that produced this message
    run_id: str              # plan run identifier (from run log)
    content: str             # message payload (freeform text or JSON string)
    message_type: str        # "request" | "response" | "broadcast"
    created_at: str          # ISO 8601 timestamp

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "step_id": self.step_id,
            "run_id": self.run_id,
            "content": self.content,
            "message_type": self.message_type,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AgentMessage:
        return cls(
            id=d["id"],
            from_agent=d["from_agent"],
            to_agent=d["to_agent"],
            step_id=d.get("step_id", ""),
            run_id=d.get("run_id", ""),
            content=d.get("content", ""),
            message_type=d.get("message_type", "request"),
            created_at=d.get("created_at", ""),
        )

    @classmethod
    def create(
        cls,
        from_agent: str,
        to_agent: str,
        content: str,
        message_type: str = "request",
        step_id: str = "",
        run_id: str = "",
        created_at: str = "",
    ) -> AgentMessage:
        """Factory that auto-generates the UUID."""
        return cls(
            id=str(uuid.uuid4()),
            from_agent=from_agent,
            to_agent=to_agent,
            step_id=step_id,
            run_id=run_id,
            content=content,
            message_type=message_type,
            created_at=created_at,
        )
```

### 2.2 SQLite Schema

Stored in a dedicated `messages.db` file alongside the plan artifacts.
Follows the same conventions as the registry DB: WAL mode, idempotent
`CREATE TABLE IF NOT EXISTS`, parameterized queries.

```sql
-- src/swarm/plan/messages.py (executed in MessageAPI.__init__)

CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    from_agent  TEXT NOT NULL,
    to_agent    TEXT NOT NULL,
    step_id     TEXT NOT NULL DEFAULT '',
    run_id      TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL DEFAULT '',
    message_type TEXT NOT NULL DEFAULT 'request'
        CHECK (message_type IN ('request', 'response', 'broadcast')),
    created_at  TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_messages_run_id
    ON messages(run_id);

CREATE INDEX IF NOT EXISTS idx_messages_to_agent_run_id
    ON messages(to_agent, run_id);

CREATE INDEX IF NOT EXISTS idx_messages_step_id
    ON messages(step_id);
```

### 2.3 MessageAPI Class

```python
# src/swarm/plan/messages.py (continued)

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class MessageAPI:
    """Persistent message bus backed by SQLite."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        """Idempotent schema creation."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id          TEXT PRIMARY KEY,
                from_agent  TEXT NOT NULL,
                to_agent    TEXT NOT NULL,
                step_id     TEXT NOT NULL DEFAULT '',
                run_id      TEXT NOT NULL DEFAULT '',
                content     TEXT NOT NULL DEFAULT '',
                message_type TEXT NOT NULL DEFAULT 'request'
                    CHECK (message_type IN ('request', 'response', 'broadcast')),
                created_at  TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_messages_run_id
                ON messages(run_id);
            CREATE INDEX IF NOT EXISTS idx_messages_to_agent_run_id
                ON messages(to_agent, run_id);
            CREATE INDEX IF NOT EXISTS idx_messages_step_id
                ON messages(step_id);
        """)

    def send(self, message: AgentMessage) -> AgentMessage:
        """Persist a message to the database.

        If ``created_at`` is empty, it is auto-populated with the current
        UTC timestamp.

        Returns the message (with ``created_at`` filled in).
        """
        created_at = message.created_at or datetime.now(tz=UTC).isoformat()
        msg = AgentMessage(
            id=message.id,
            from_agent=message.from_agent,
            to_agent=message.to_agent,
            step_id=message.step_id,
            run_id=message.run_id,
            content=message.content,
            message_type=message.message_type,
            created_at=created_at,
        )
        self._conn.execute(
            """
            INSERT INTO messages (id, from_agent, to_agent, step_id, run_id,
                                  content, message_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (msg.id, msg.from_agent, msg.to_agent, msg.step_id,
             msg.run_id, msg.content, msg.message_type, msg.created_at),
        )
        self._conn.commit()
        return msg

    def receive(
        self,
        to_agent: str,
        run_id: str,
        since: str = "",
        limit: int = 100,
    ) -> list[AgentMessage]:
        """Retrieve messages addressed to a specific agent in a run.

        Also includes broadcast messages (to_agent='*') for the same run.

        Args:
            to_agent: The receiving agent type.
            run_id: The plan run identifier.
            since: Optional ISO timestamp; only return messages after this time.
            limit: Maximum number of messages to return (newest first).

        Returns:
            List of ``AgentMessage`` ordered by ``created_at`` descending.
        """
        if since:
            rows = self._conn.execute(
                """
                SELECT id, from_agent, to_agent, step_id, run_id,
                       content, message_type, created_at
                FROM messages
                WHERE (to_agent = ? OR to_agent = '*') AND run_id = ?
                  AND created_at > ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (to_agent, run_id, since, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT id, from_agent, to_agent, step_id, run_id,
                       content, message_type, created_at
                FROM messages
                WHERE (to_agent = ? OR to_agent = '*') AND run_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (to_agent, run_id, limit),
            ).fetchall()

        return [self._row_to_message(r) for r in rows]

    def broadcast(
        self,
        from_agent: str,
        content: str,
        run_id: str,
        step_id: str = "",
    ) -> AgentMessage:
        """Send a broadcast message (to_agent='*') visible to all agents.

        Returns the persisted ``AgentMessage``.
        """
        msg = AgentMessage.create(
            from_agent=from_agent,
            to_agent="*",
            content=content,
            message_type="broadcast",
            step_id=step_id,
            run_id=run_id,
        )
        return self.send(msg)

    def list_by_run(self, run_id: str, limit: int = 500) -> list[AgentMessage]:
        """Return all messages for a given run, ordered by creation time.

        Args:
            run_id: The plan run identifier.
            limit: Maximum number of messages to return.

        Returns:
            List of ``AgentMessage`` ordered by ``created_at`` ascending.
        """
        rows = self._conn.execute(
            """
            SELECT id, from_agent, to_agent, step_id, run_id,
                   content, message_type, created_at
            FROM messages
            WHERE run_id = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (run_id, limit),
        ).fetchall()
        return [self._row_to_message(r) for r in rows]

    def list_by_step(self, step_id: str, limit: int = 100) -> list[AgentMessage]:
        """Return all messages produced by a given step.

        Args:
            step_id: The plan step identifier.
            limit: Maximum number of messages to return.

        Returns:
            List of ``AgentMessage`` ordered by ``created_at`` ascending.
        """
        rows = self._conn.execute(
            """
            SELECT id, from_agent, to_agent, step_id, run_id,
                   content, message_type, created_at
            FROM messages
            WHERE step_id = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (step_id, limit),
        ).fetchall()
        return [self._row_to_message(r) for r in rows]

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    @staticmethod
    def _row_to_message(row: tuple[str, ...]) -> AgentMessage:
        return AgentMessage(
            id=row[0],
            from_agent=row[1],
            to_agent=row[2],
            step_id=row[3],
            run_id=row[4],
            content=row[5],
            message_type=row[6],
            created_at=row[7],
        )
```

### 2.4 MCP Tools

Three new MCP tools in `src/swarm/mcp/message_tools.py`.  Follows the same
pattern as `artifact_tools.py`: string params in, JSON string out.

```python
# src/swarm/mcp/message_tools.py

from __future__ import annotations

import json
from pathlib import Path

from swarm.mcp import state
from swarm.mcp.instance import mcp
from swarm.plan.messages import AgentMessage, MessageAPI


def _get_message_api() -> MessageAPI:
    """Resolve the MessageAPI, creating it lazily from the plans directory."""
    plans_dir = Path(state.plans_dir) if state.plans_dir else Path.cwd()
    db_path = plans_dir / "messages.db"
    return MessageAPI(db_path)


@mcp.tool()
def agent_send_message(
    from_agent: str,
    to_agent: str,
    content: str,
    run_id: str,
    step_id: str = "",
    message_type: str = "request",
) -> str:
    """Send a message from one agent to another within a plan run.

    Args:
        from_agent: Agent type of the sender.
        to_agent: Agent type of the receiver. Use '*' for broadcast.
        content: Message content (freeform text or JSON string).
        run_id: Plan run identifier (from the run log).
        step_id: Optional step ID that produced this message.
        message_type: One of 'request', 'response', 'broadcast'.

    Returns:
        JSON ``{"ok": true, "message": {...}}`` with the persisted message,
        or ``{"error": "..."}`` on validation failure.
    """
    if message_type not in ("request", "response", "broadcast"):
        return json.dumps({
            "error": f"Invalid message_type '{message_type}'; "
                     f"must be 'request', 'response', or 'broadcast'"
        })

    if not from_agent:
        return json.dumps({"error": "from_agent is required"})
    if not to_agent:
        return json.dumps({"error": "to_agent is required"})
    if not run_id:
        return json.dumps({"error": "run_id is required"})

    api = _get_message_api()
    try:
        msg = AgentMessage.create(
            from_agent=from_agent,
            to_agent=to_agent,
            content=content,
            message_type=message_type,
            step_id=step_id,
            run_id=run_id,
        )
        persisted = api.send(msg)
        return json.dumps({"ok": True, "message": persisted.to_dict()})
    finally:
        api.close()


@mcp.tool()
def agent_receive_messages(
    to_agent: str,
    run_id: str,
    since: str = "",
    limit: str = "100",
) -> str:
    """Retrieve messages addressed to a specific agent in a plan run.

    Includes both direct messages and broadcasts (to_agent='*').

    Args:
        to_agent: Agent type to receive messages for.
        run_id: Plan run identifier.
        since: Optional ISO timestamp; only return messages created after
            this time.
        limit: Maximum number of messages to return (default '100').

    Returns:
        JSON array of message objects, newest first.
    """
    try:
        max_messages = int(limit)
    except ValueError:
        return json.dumps({"error": f"Invalid limit: {limit!r}"})

    api = _get_message_api()
    try:
        messages = api.receive(
            to_agent=to_agent, run_id=run_id, since=since, limit=max_messages,
        )
        return json.dumps([m.to_dict() for m in messages])
    finally:
        api.close()


@mcp.tool()
def agent_broadcast(
    from_agent: str,
    content: str,
    run_id: str,
    step_id: str = "",
) -> str:
    """Broadcast a message to all agents in a plan run.

    Shorthand for ``agent_send_message`` with ``to_agent='*'`` and
    ``message_type='broadcast'``.

    Args:
        from_agent: Agent type of the sender.
        content: Message content.
        run_id: Plan run identifier.
        step_id: Optional step ID that produced this message.

    Returns:
        JSON ``{"ok": true, "message": {...}}`` with the persisted message.
    """
    if not from_agent:
        return json.dumps({"error": "from_agent is required"})
    if not run_id:
        return json.dumps({"error": "run_id is required"})

    api = _get_message_api()
    try:
        persisted = api.broadcast(
            from_agent=from_agent,
            content=content,
            run_id=run_id,
            step_id=step_id,
        )
        return json.dumps({"ok": True, "message": persisted.to_dict()})
    finally:
        api.close()
```

### 2.5 PlanStep Integration: `message_to` Field

```python
# src/swarm/plan/models.py  (PlanStep class)
message_to: str = ""  # NEW: target agent for automatic message routing
```

Serialization (sparse):

```python
# to_dict:
if self.message_to:
    d["message_to"] = self.message_to

# from_dict:
message_to=d.get("message_to", ""),
```

#### Executor Integration

When a step with `message_to` set completes successfully, the executor reads
the step's output artifact and sends it as a message to the named agent.

```python
# In execute_foreground, after record_success:
if step.message_to and step.output_artifact:
    _send_step_output_as_message(run_state, step)


def _send_step_output_as_message(run_state: RunState, step: PlanStep) -> None:
    """Route step output as a message to the designated agent."""
    artifact_path = run_state.artifacts_dir / step.output_artifact
    if not artifact_path.exists():
        logger.warning(
            "message_routing_skipped",
            step_id=step.id,
            reason="output artifact missing",
        )
        return

    content = artifact_path.read_text(encoding="utf-8", errors="replace")
    # Truncate to a reasonable size for a message (64 KB)
    if len(content) > 65536:
        content = content[:65536] + "\n... [truncated]"

    run_id = run_state.log.plan_path  # Use plan_path as run_id for now
    db_path = run_state.artifacts_dir.parent / "messages.db"
    api = MessageAPI(db_path)
    try:
        api.send(AgentMessage.create(
            from_agent=step.agent_type,
            to_agent=step.message_to,
            content=content,
            message_type="response",
            step_id=step.id,
            run_id=run_id,
        ))
    finally:
        api.close()
    logger.info(
        "message_sent",
        step_id=step.id,
        from_agent=step.agent_type,
        to_agent=step.message_to,
    )
```

### 2.6 Join Steps with Message Aggregation

Join steps can aggregate messages from upstream agents in addition to
(or instead of) requiring file artifacts.  The join step's agent receives
all messages from its upstream dependencies as context.

```python
# In handle_join, before execute_foreground:
if step.message_to or step.required_inputs:
    # Inject upstream messages into the step prompt
    db_path = run_state.artifacts_dir.parent / "messages.db"
    api = MessageAPI(db_path)
    try:
        run_id = run_state.log.plan_path
        upstream_messages = []
        for dep_id in step.depends_on:
            msgs = api.list_by_step(dep_id)
            upstream_messages.extend(msgs)
        if upstream_messages:
            msg_context = "\n\n--- Upstream Messages ---\n"
            for msg in upstream_messages:
                msg_context += (
                    f"[{msg.from_agent} -> {msg.to_agent}] "
                    f"({msg.message_type}): {msg.content}\n"
                )
            # Patch the step's prompt with message context
            # (uses dataclass replacement since PlanStep is frozen)
            enriched_step = PlanStep(
                id=step.id,
                type=step.type,
                prompt=step.prompt + msg_context,
                agent_type=step.agent_type,
                depends_on=step.depends_on,
                output_artifact=step.output_artifact,
                required_inputs=step.required_inputs,
                on_failure=step.on_failure,
                spawn_mode=step.spawn_mode,
                condition=step.condition,
                required_tools=step.required_tools,
                critic_agent=step.critic_agent,
                max_critic_iterations=step.max_critic_iterations,
                retry_config=step.retry_config,
                message_to=step.message_to,
            )
            execute_foreground(run_state, enriched_step)
            return
    finally:
        api.close()
execute_foreground(run_state, step)
```

### 2.7 MCP State Extension

```python
# src/swarm/mcp/state.py
message_api: MessageAPI | None = None
```

The `MessageAPI` is initialized lazily in the MCP tools rather than in
`state` because messages.db is scoped to the plans directory, which may
change between calls.  The `_get_message_api()` helper in
`message_tools.py` handles this.

### 2.8 Example Usage

#### Example: Code Review Pipeline with Message Passing

```json
{
  "version": 1,
  "goal": "Multi-agent code review with message coordination",
  "steps": [
    {
      "id": "analyze",
      "type": "task",
      "prompt": "Analyze the codebase for security issues",
      "agent_type": "security-auditor",
      "output_artifact": "security-report.md",
      "message_to": "code-reviewer"
    },
    {
      "id": "lint",
      "type": "task",
      "prompt": "Run linting and style checks",
      "agent_type": "linter",
      "output_artifact": "lint-report.md",
      "message_to": "code-reviewer"
    },
    {
      "id": "review",
      "type": "join",
      "prompt": "Synthesize all findings into a final review",
      "agent_type": "code-reviewer",
      "depends_on": ["analyze", "lint"],
      "output_artifact": "final-review.md"
    }
  ]
}
```

**How it works**: The `analyze` and `lint` steps run in parallel (no
dependency between them).  When each completes, its output artifact content
is automatically sent as a message to `code-reviewer`.  When the `review`
join step runs, its agent receives the upstream messages appended to its
prompt, giving it access to both reports without having to read files.

#### Example: MCP Tool Usage from an Agent

An agent running inside a step can use the MCP tools directly:

```
# Security auditor sends a priority alert
agent_send_message(
    from_agent="security-auditor",
    to_agent="code-reviewer",
    content='{"severity":"critical","finding":"SQL injection in auth.py:42"}',
    run_id="run-001",
    step_id="analyze",
    message_type="request"
)

# Code reviewer checks for messages
agent_receive_messages(
    to_agent="code-reviewer",
    run_id="run-001"
)
# Returns: [{"id":"...","from_agent":"security-auditor","content":"...","message_type":"request",...}]

# Broadcast to all agents in the run
agent_broadcast(
    from_agent="orchestrator",
    content="Deadline moved up -- prioritize critical findings only",
    run_id="run-001"
)
```

### 2.9 Testing Strategy

| Test area | Technique |
|---|---|
| `AgentMessage` serde | Round-trip `to_dict` / `from_dict` with all field combinations |
| `AgentMessage.create` | Verify UUID generation, field passthrough |
| `MessageAPI` init | `tmp_path` fixture, verify `messages.db` created with WAL mode |
| `MessageAPI.send` | Insert a message, read it back via raw SQL, verify all columns |
| `MessageAPI.receive` | Send 5 messages (3 direct, 2 broadcast), verify `receive` returns correct subset; test `since` filter |
| `MessageAPI.broadcast` | Verify `to_agent='*'` and `message_type='broadcast'` |
| `MessageAPI.list_by_run` | Send messages across two runs, verify isolation |
| `MessageAPI.list_by_step` | Send messages from two steps, verify per-step filtering |
| `agent_send_message` MCP tool | Integration test with `tmp_path` plans dir, verify JSON response shape |
| `agent_receive_messages` MCP tool | Send then receive, verify round-trip |
| `agent_broadcast` MCP tool | Broadcast then receive, verify `to_agent='*'` |
| Validation | Invalid `message_type`, empty `from_agent`, empty `run_id` -- all return error JSON |
| `message_to` executor integration | Mock `launch_agent`, verify message sent after step success, verify skipped on step failure |
| Join message aggregation | Set up 2 upstream steps with messages, verify join step prompt is enriched |
| Concurrency safety | WAL mode allows concurrent reads; test with two `MessageAPI` instances on same DB |

**Test count estimate**: ~30 new tests in `tests/plan/test_messages.py` and
`tests/mcp/test_message_tools.py`.

---

## Summary of All Changes

### New Files

| File | Purpose |
|---|---|
| `src/swarm/plan/messages.py` | `AgentMessage` dataclass, `MessageAPI` class, SQLite schema |
| `src/swarm/mcp/message_tools.py` | 3 MCP tools: `agent_send_message`, `agent_receive_messages`, `agent_broadcast` |
| `tests/plan/test_messages.py` | Unit tests for message bus |
| `tests/mcp/test_message_tools.py` | Integration tests for message MCP tools |

### Modified Files

| File | Changes |
|---|---|
| `src/swarm/plan/conditions.py` | Add `output_contains:` prefix, `import re` |
| `src/swarm/plan/models.py` | Add `ConditionalAction`, `DecisionConfig` dataclasses; add `decision_config`, `message_to` fields to `PlanStep`; add `max_replans` to `Plan` |
| `src/swarm/plan/parser.py` | Add `"decision"` to `_VALID_STEP_TYPES`; validate `DecisionConfig` |
| `src/swarm/plan/executor.py` | Add `handle_decision`; add `replan_count` to `RunState`; add `message_to` routing after step success; extend join step with message aggregation |
| `src/swarm/plan/run_log.py` | Add `replan_count` field to `RunLog` |
| `src/swarm/mcp/plan_tools.py` | Add `plan_replan` MCP tool |
| `src/swarm/mcp/state.py` | Add `message_api` variable |

### New MCP Tools (4 total, bringing the total from 31 to 35)

| Tool | Purpose |
|---|---|
| `plan_replan` | Insert remediation steps mid-run with safety limits |
| `agent_send_message` | Send a message from one agent to another |
| `agent_receive_messages` | Retrieve messages for an agent in a run |
| `agent_broadcast` | Broadcast a message to all agents |

### New Condition Type

| Condition | Format | Behavior |
|---|---|---|
| `output_contains` | `output_contains:<step_id>:<regex>` | True if step's stdout log matches the regex |

### New Step Type

| Type | Purpose |
|---|---|
| `decision` | Evaluate conditions and activate/skip downstream branches without launching a subprocess |
