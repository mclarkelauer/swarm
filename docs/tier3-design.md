# Tier 3 — Smarter Execution: Design Specification

## Feature 1: plan_execute_step MCP Tool

**File:** `src/swarm/mcp/plan_tools.py`

### MCP Tool Signature

```python
@mcp.tool()
def plan_execute_step(
    plan_path: str,
    step_id: str,
    variables_json: str = "{}",
) -> str:
```

### Logic

1. Load plan from `plan_path` via `load_plan(Path(plan_path))`. File not found → `{"error": "Plan file not found: <path>"}`
2. Find step by `step_id`. Not found → `{"error": "Step '<id>' not found in plan"}`
3. Merge variables: `plan.variables` updated with `json.loads(variables_json)`. Invalid JSON → `{"error": "Invalid variables_json: ..."}`
4. Interpolate prompt using safe partial formatting — replace `{key}` only when key is in merged vars, leave unreplaced placeholders as-is:

```python
import re

def _safe_interpolate(template: str, variables: dict[str, str]) -> str:
    def _replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        return variables.get(key, match.group(0))
    return re.sub(r"\{(\w+)\}", _replacer, template)
```

5. Resolve agent via `state.registry_api.resolve_agent(step.agent_type)`, catch `RegistryError`

### Return Format

**Agent found in registry:**
```json
{
  "agent_type": "code-reviewer",
  "prompt": "Review the API module for security issues",
  "spawn_mode": "foreground",
  "output_artifact": "review.md",
  "description": "Reviews Python code for security vulnerabilities",
  "tools": ["Read", "Grep", "Bash"]
}
```

**Agent NOT found:**
```json
{
  "agent_type": "unknown-agent",
  "prompt": "Do the work",
  "spawn_mode": "foreground",
  "output_artifact": "",
  "description": null,
  "tools": null
}
```

`description` and `tools` are `null` (not omitted) to signal registry resolution failed.

---

## Feature 2: Conditional Step Gating

### Model Change

**File:** `src/swarm/plan/models.py`

Add to `PlanStep` after `spawn_mode`:

```python
condition: str = ""
```

Sparse serialization in `to_dict()`:
```python
if self.condition:
    d["condition"] = self.condition
```

Deserialization in `from_dict()`:
```python
condition=d.get("condition", ""),
```

### Expression Language

| Expression | Meaning |
|---|---|
| `""` | Always execute (default) |
| `"always"` | Always execute (explicit) |
| `"never"` | Skip this step |
| `"artifact_exists:<path>"` | Execute only if file exists (relative to artifacts_dir) |
| `"step_completed:<step_id>"` | Execute only if step_id is in completed set |
| `"step_failed:<step_id>"` | Execute only if step_outcomes maps step_id to "failed" |

### New Module: `src/swarm/plan/conditions.py`

```python
def validate_condition(condition: str) -> str | None:
    """Return error message if invalid, None if valid."""

def evaluate_condition(
    condition: str,
    completed: set[str],
    step_outcomes: dict[str, str] | None = None,
    artifacts_dir: Path | None = None,
) -> bool:
    """Return True if step should execute."""
```

- `""` or `"always"` → True
- `"never"` → False
- `"artifact_exists:<path>"` → check `(artifacts_dir / path).exists()`, True if artifacts_dir is None (permissive fallback)
- `"step_completed:<id>"` → `id in completed`
- `"step_failed:<id>"` → `step_outcomes.get(id) == "failed"`, False if step_outcomes is None
- Unknown format → True (permissive)

### DAG Integration

**File:** `src/swarm/plan/dag.py`

Add `step_outcomes: dict[str, str] | None = None` parameter to `get_ready_steps`:

```python
def get_ready_steps(
    plan: Plan,
    completed: set[str],
    artifacts_dir: Path | None = None,
    step_outcomes: dict[str, str] | None = None,
) -> list[PlanStep]:
```

After existing dependency and required_inputs checks:
```python
if not evaluate_condition(s.condition, completed, step_outcomes=step_outcomes, artifacts_dir=artifacts_dir):
    continue
```

### Validation

**File:** `src/swarm/plan/parser.py`

Add to per-step loop in `validate_plan()`:
```python
cond_error = validate_condition(step.condition)
if cond_error is not None:
    errors.append(f"Step '{step.id}': {cond_error}")
```

### MCP Tool Update

**File:** `src/swarm/mcp/plan_tools.py`

Add `step_outcomes_json: str = "{}"` parameter to `plan_get_ready_steps`:
```python
outcomes: dict[str, str] = json.loads(step_outcomes_json) if step_outcomes_json else {}
ready = get_ready_steps(plan, completed, artifacts_dir=art_dir, step_outcomes=outcomes or None)
```

---

## Feature 3: Semantic Re-ranking

### New Module: `src/swarm/forge/ranking.py`

```python
def build_ranking_prompt(query: str, candidates: list[AgentDefinition]) -> str:
    """Produce prompt asking LLM to rank candidates by relevance."""
```

Format:
```
You are ranking agent definitions by relevance to a task.

Task: <query>

Candidates:
  1. agent-name — description or (no description)
  2. ...

Rank these candidates from most relevant to least relevant.
Return ONLY a comma-separated list of the candidate numbers
in order of relevance (e.g. '3, 1, 2').
```

```python
def parse_ranking_response(response: str, candidates: list[AgentDefinition]) -> list[AgentDefinition]:
    """Parse LLM ranking response, reorder candidates. Fallback to original order."""
```

Parsing strategy:
1. Extract numbers via `re.findall(r"\d+", response)`, map to 1-based candidate indices
2. Fallback: try matching agent names line by line
3. Final fallback: return original order
4. Always append unmentioned candidates at end

### New MCP Tool

**File:** `src/swarm/mcp/forge_tools.py`

```python
@mcp.tool()
def forge_suggest_ranked(query: str) -> str:
    """Search for agents and provide a ranking prompt for the orchestrator."""
```

Returns `{"candidates": [...], "ranking_prompt": "..."}`. Candidates use `_agent_summary` (truncated prompts). The orchestrator evaluates ranking_prompt itself — Swarm stays LLM-agnostic.

---

## Feature 4: CLI Improvements

### 4a. `swarm run --latest`

**File:** `src/swarm/cli/run_cmd.py`

- Change `path` argument: `required=False, default=None`, remove `exists=True` constraint
- Add `--latest` flag: `is_flag=True`
- Logic: if `--latest`, scan cwd with `list_versions()`, pick highest, construct path
- Error if neither `path` nor `--latest` provided
- Error if `--latest` but no `plan_v*.json` found

### 4b. `swarm status`

**New file:** `src/swarm/cli/status_cmd.py`

- Reads `run_log.json` (configurable via `--log-file`)
- Cross-references plan file (from `log.plan_path`) to get step type and agent_type
- Prints header: plan path, version, status (color-coded), progress (X/Y)
- Prints Rich table: Step ID, Type, Agent, Status, Duration, Message
- Duration computed from `started_at`/`finished_at` timestamps
- Handle missing run_log.json gracefully

**Registration in `src/swarm/cli/main.py`:**
```python
from swarm.cli.status_cmd import status
cli.add_command(status)
```

---

## Affected Files

### Files to CREATE

| File | Purpose |
|---|---|
| `src/swarm/plan/conditions.py` | `validate_condition()` and `evaluate_condition()` |
| `src/swarm/forge/ranking.py` | `build_ranking_prompt()` and `parse_ranking_response()` |
| `src/swarm/cli/status_cmd.py` | `swarm status` command |
| `tests/test_plan_conditions.py` | Tests for conditions |
| `tests/test_forge_ranking.py` | Tests for ranking |
| `tests/test_cli_status.py` | Tests for status command |

### Files to MODIFY

| File | Changes |
|---|---|
| `src/swarm/plan/models.py` | Add `condition` field to PlanStep |
| `src/swarm/plan/dag.py` | Add `step_outcomes` param, call `evaluate_condition` |
| `src/swarm/plan/parser.py` | Add condition validation |
| `src/swarm/mcp/plan_tools.py` | Add `plan_execute_step`, update `plan_get_ready_steps` |
| `src/swarm/mcp/forge_tools.py` | Add `forge_suggest_ranked` |
| `src/swarm/cli/run_cmd.py` | Make path optional, add `--latest` |
| `src/swarm/cli/main.py` | Register status command |

## Implementation Order

1. `conditions.py` — zero dependencies, pure logic
2. `models.py` — add condition field
3. `parser.py` — add condition validation
4. `dag.py` — integrate evaluate_condition
5. `ranking.py` — standalone module
6. `plan_tools.py` — add plan_execute_step, update plan_get_ready_steps
7. `forge_tools.py` — add forge_suggest_ranked
8. `run_cmd.py` — add --latest
9. `status_cmd.py` + `main.py` — new status command
