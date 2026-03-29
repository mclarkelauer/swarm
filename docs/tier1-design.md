# Tier 1 — Model Enrichment Design Specification

## 1. AgentDefinition Changes

**File:** `src/swarm/registry/models.py`

Two new fields added to the frozen dataclass, positioned after `working_dir` and before `source`:

```python
description: str = ""
tags: tuple[str, ...] = ()
```

**`to_dict()` changes:** Add two keys. `tags` serialized as list (matching convention for `tools`/`permissions`):

```python
"description": self.description,
"tags": list(self.tags),
```

**`from_dict()` changes:** Safe defaults for backward compat with existing cache/plan files:

```python
description=d.get("description", ""),
tags=tuple(d.get("tags", [])),
```

---

## 2. SQLite Schema Migration

**File:** `src/swarm/registry/db.py`

### Updated CREATE TABLE (new databases)

Add two columns after `system_prompt`:

```sql
description TEXT NOT NULL DEFAULT '',
tags        TEXT NOT NULL DEFAULT '[]',
```

`tags` stored as JSON-encoded string (e.g. `'["code-review","python"]'`), matching convention for `tools`/`permissions`.

### ALTER TABLE (existing databases)

After the CREATE TABLE block, add idempotent migration:

```python
for col, default in [("description", "''"), ("tags", "'[]'")]:
    try:
        conn.execute(f"ALTER TABLE agents ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}")
    except sqlite3.OperationalError:
        pass  # Column already exists
```

---

## 3. RegistryAPI Changes

**File:** `src/swarm/registry/api.py`

**`_SELECT_COLS`:** Append new columns:

```python
_SELECT_COLS = (
    "id, name, parent_id, system_prompt, tools, permissions, "
    "working_dir, source, created_at, description, tags"
)
```

**`_row_to_definition()`:** Add at positions 9 and 10:

```python
description=row[9],
tags=tuple(json.loads(row[10])),
```

**`create()`:** Add `description: str = ""` and `tags: list[str] | None = None` parameters. Default `tags` to `[]` when `None`. Include both in the `AgentDefinition` constructor and INSERT statement.

**`clone()`:** Propagate from original when not overridden:

```python
description=data.get("description", original.description),
tags=tuple(data.get("tags", list(original.tags))),
```

INSERT gains two new columns.

**`search()`:** Extend WHERE to also match description and tags:

```sql
WHERE name LIKE ? OR system_prompt LIKE ? OR description LIKE ? OR tags LIKE ?
```

All four use the same `%query%` parameter.

**`inspect()`:** No direct change needed — calls `defn.to_dict()` which includes new fields automatically.

---

## 4. ForgeAPI Changes

**File:** `src/swarm/forge/api.py`

**`create_agent()`:** Add `description: str = ""` and `tags: list[str] | None = None` parameters. Pass through to `self._registry.create()`.

**`clone_agent()`:** No signature change needed. The `overrides` dict can already contain `"description"` and `"tags"` keys.

---

## 5. Cache Changes

**File:** `src/swarm/forge/cache.py`

No code changes required. `write_cache` calls `definition.to_dict()` (includes new fields). `read_cache` calls `AgentDefinition.from_dict()` (uses `.get()` with defaults). Old cache files missing keys deserialize correctly.

---

## 6. PlanStep Changes

**File:** `src/swarm/plan/models.py`

Four new fields added to `PlanStep` frozen dataclass, positioned after `checkpoint_config`:

```python
output_artifact: str = ""
required_inputs: tuple[str, ...] = ()
on_failure: str = "stop"
spawn_mode: str = "foreground"
```

| Field | Type | Default | Description |
|---|---|---|---|
| `output_artifact` | `str` | `""` | Expected output file path this step produces |
| `required_inputs` | `tuple[str, ...]` | `()` | Artifact paths that must exist before step runs |
| `on_failure` | `str` | `"stop"` | Behavior on failure: `stop`, `skip`, `retry` |
| `spawn_mode` | `str` | `"foreground"` | Launch mode: `foreground`, `background` |

**`to_dict()` changes:** Sparse serialization (only include when non-default):

```python
if self.output_artifact:
    d["output_artifact"] = self.output_artifact
if self.required_inputs:
    d["required_inputs"] = list(self.required_inputs)
if self.on_failure != "stop":
    d["on_failure"] = self.on_failure
if self.spawn_mode != "foreground":
    d["spawn_mode"] = self.spawn_mode
```

**`from_dict()` changes:**

```python
output_artifact=d.get("output_artifact", ""),
required_inputs=tuple(d.get("required_inputs", [])),
on_failure=d.get("on_failure", "stop"),
spawn_mode=d.get("spawn_mode", "foreground"),
```

---

## 7. Validation Changes

**File:** `src/swarm/plan/parser.py`

Add constants:

```python
_VALID_ON_FAILURE = {"stop", "skip", "retry"}
_VALID_SPAWN_MODES = {"foreground", "background"}
```

Add validation in `validate_plan()` per-step loop:

```python
if step.on_failure not in _VALID_ON_FAILURE:
    errors.append(
        f"Step '{step.id}' has invalid on_failure '{step.on_failure}'; "
        f"must be one of {sorted(_VALID_ON_FAILURE)}"
    )

if step.spawn_mode not in _VALID_SPAWN_MODES:
    errors.append(
        f"Step '{step.id}' has invalid spawn_mode '{step.spawn_mode}'; "
        f"must be one of {sorted(_VALID_SPAWN_MODES)}"
    )

for inp in step.required_inputs:
    if not inp:
        errors.append(f"Step '{step.id}' has an empty string in required_inputs")
```

---

## 8. DAG Logic Changes

**File:** `src/swarm/plan/dag.py`

Change `get_ready_steps` signature:

```python
def get_ready_steps(
    plan: Plan,
    completed: set[str],
    artifacts_dir: Path | None = None,
) -> list[PlanStep]:
```

Add `from pathlib import Path` to imports.

Logic: a step is ready when (a) not already completed, (b) all `depends_on` IDs are in `completed`, AND (c) when `artifacts_dir` is provided, all `required_inputs` paths exist:

```python
ready: list[PlanStep] = []
for s in plan.steps:
    if s.id in completed:
        continue
    if not all(d in completed for d in s.depends_on):
        continue
    if artifacts_dir is not None and s.required_inputs:
        if not all((artifacts_dir / inp).exists() for inp in s.required_inputs):
            continue
    ready.append(s)
return ready
```

When `artifacts_dir` is `None`, file-existence check is skipped for backward compatibility.

---

## 9. MCP Tool Surface Changes

### forge_create

**File:** `src/swarm/mcp/forge_tools.py`

Add parameters:

```python
def forge_create(
    name: str,
    system_prompt: str,
    tools: str = "[]",
    permissions: str = "[]",
    description: str = "",
    tags: str = "[]",
) -> str:
```

Parse tags: `tag_list: list[str] = json.loads(tags) if tags else []`
Pass `description` and `tags=tag_list` to `state.forge_api.create_agent()`.

### forge_clone

Add `description: str = ""` and `tags: str = ""` parameters. When non-empty, add to overrides:

```python
if description:
    overrides["description"] = description
if tags:
    overrides["tags"] = json.loads(tags)
```

### forge_list and forge_suggest

Truncate `system_prompt` to 80 chars in output. Add helper:

```python
def _agent_summary(a: AgentDefinition) -> dict:
    d = a.to_dict()
    d["system_prompt"] = d["system_prompt"][:80]
    return d
```

Use: `return json.dumps([_agent_summary(a) for a in agents])`

### plan_get_ready_steps

**File:** `src/swarm/mcp/plan_tools.py`

Add `artifacts_dir: str = ""` parameter:

```python
art_dir = Path(artifacts_dir) if artifacts_dir else None
ready = get_ready_steps(plan, completed, artifacts_dir=art_dir)
```

### registry_inspect

No change needed — `to_dict()` includes new fields automatically.

---

## 10. Affected Files

### Registry subsystem
- `src/swarm/registry/models.py` — add `description`, `tags` fields
- `src/swarm/registry/db.py` — schema migration + updated CREATE TABLE
- `src/swarm/registry/api.py` — update queries, create, clone, search
- `src/swarm/registry/sources/project.py` — read new fields from `.agent.json`

### Forge subsystem
- `src/swarm/forge/api.py` — update `create_agent` signature
- `src/swarm/forge/cache.py` — no changes needed
- `src/swarm/forge/prompts.py` — update system prompt and build function

### Plan subsystem
- `src/swarm/plan/models.py` — add four PlanStep fields
- `src/swarm/plan/parser.py` — add validation rules
- `src/swarm/plan/dag.py` — add `artifacts_dir` parameter

### MCP tools
- `src/swarm/mcp/forge_tools.py` — update forge_create, forge_clone, forge_list, forge_suggest
- `src/swarm/mcp/plan_tools.py` — update plan_get_ready_steps
- `src/swarm/mcp/registry_tools.py` — no changes needed

### CLI
- `src/swarm/cli/registry_cmd.py` — add description/tags to commands
- `src/swarm/cli/forge_cmd.py` — add description/tags to commands

---

## 11. Implementation Order

1. `registry/models.py` — add fields (all existing tests still pass via defaults)
2. `registry/db.py` — schema migration
3. `registry/api.py` — update SQL and API methods
4. `forge/api.py` — update `create_agent` signature
5. `plan/models.py` — add PlanStep fields (existing tests pass via defaults)
6. `plan/parser.py` — add validation rules
7. `plan/dag.py` — add `artifacts_dir` parameter
8. MCP tools — update all tool files
9. CLI commands — update registry_cmd and forge_cmd
10. Documentation — update `design.md`
