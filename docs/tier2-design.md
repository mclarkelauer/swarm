# Tier 2 — Bridge Tools and Artifact Query System: Design Specification

## Key Design Decision: No pyyaml

PyYAML is not a project dependency. Claude Code agent frontmatter is a trivially small subset of YAML (scalars and lists only). A **minimal custom frontmatter parser** (~40 lines) in `src/swarm/forge/frontmatter.py` handles the exact subset needed, avoiding a new dependency.

---

## Tool 1: `forge_export_subagent`

**Purpose:** Write a `.claude/agents/<name>.md` file from a registry AgentDefinition, bridging Swarm agents into Claude Code's native subagent format.

### MCP Tool Signature

```python
@mcp.tool()
def forge_export_subagent(
    agent_id: str = "",
    name: str = "",
    output_dir: str = "",
) -> str:
```

### Resolution Logic

1. If `agent_id` non-empty → `state.registry_api.resolve_agent(agent_id)`
2. Else if `name` non-empty → `state.registry_api.resolve_agent(name)`
3. Else → return `{"error": "Supply agent_id or name"}`
4. Catch `RegistryError` → return `{"error": str(exc)}`

### Output Directory

- If `output_dir` non-empty → `Path(output_dir)`
- Else → `Path.cwd() / ".claude" / "agents"`
- Create with `mkdir(parents=True, exist_ok=True)`

### File Template

Filename: `<defn.name>.md`

```markdown
---
name: <defn.name>
description: <defn.description>
tools:
  - <tool1>
  - <tool2>
---

<defn.system_prompt>
```

**Empty field handling:**
- `description`: omit line if empty
- `tools`: omit block if empty tuple
- `permissions`, `tags`: NOT included (Swarm-specific, no Claude Code equivalent)

### Rendering Function

In `src/swarm/forge/frontmatter.py`:

```python
def render_frontmatter(defn: AgentDefinition) -> str:
    lines = ["---"]
    lines.append(f"name: {defn.name}")
    if defn.description:
        lines.append(f"description: {defn.description}")
    if defn.tools:
        lines.append("tools:")
        for tool in defn.tools:
            lines.append(f"  - {tool}")
    lines.append("---")
    lines.append("")
    lines.append(defn.system_prompt)
    return "\n".join(lines) + "\n"
```

### Return Format

```json
{"ok": true, "path": "/absolute/path/to/.claude/agents/code-reviewer.md"}
```

### Registration

Add in `src/swarm/mcp/forge_tools.py`.

---

## Tool 2: `forge_import_subagents`

**Purpose:** Read `.claude/agents/*.md` files, parse YAML frontmatter + body, register in Swarm registry.

### MCP Tool Signature

```python
@mcp.tool()
def forge_import_subagents(project_dir: str = "") -> str:
```

### Directory Resolution

- If `project_dir` non-empty → `Path(project_dir) / ".claude" / "agents"`
- Else → `Path.cwd() / ".claude" / "agents"`
- If directory doesn't exist → return `{"imported": [], "skipped": [], "errors": []}`

### Frontmatter Parser

New module: `src/swarm/forge/frontmatter.py`

```python
def parse_frontmatter(text: str) -> tuple[dict[str, str | list[str]], str]:
    """Parse YAML frontmatter and body from a markdown document.

    Returns:
        (metadata_dict, body_text)

    Raises:
        ValueError: If no valid frontmatter delimiters found.
    """
```

Parser logic:
1. Strip leading whitespace. Confirm starts with `---\n`.
2. Find second `---\n` (or `---` at EOF). Extract block between delimiters.
3. Parse line by line:
   - `key: value` → scalar string entry (split on first `: ` only, handles colons in values)
   - `key:` followed by `  - item` lines → list entry
   - `key: [item1, item2]` inline form → list entry (strip brackets, split commas)
4. Body = everything after closing `---`, stripped of leading blank lines.

### Field Mapping

| Frontmatter key | AgentDefinition field | Notes |
|---|---|---|
| `name` | `name` | Required. Skip file if missing. |
| `description` | `description` | Optional, default `""` |
| `tools` | `tools` | Optional, default `()` |
| (body) | `system_prompt` | Markdown body becomes system prompt |

Additional frontmatter keys silently ignored.

### Conflict Resolution

- Before registering, check `state.registry_api.list_agents(name_filter=name)` for exact name match
- If found → add to `skipped` list
- If not found → register via `state.forge_api.create_agent()`

### Error Handling

- Malformed files (no frontmatter, missing name) → add to `errors` list, continue processing

### Return Format

```json
{
  "imported": ["code-reviewer", "doc-writer"],
  "skipped": ["existing-agent"],
  "errors": ["bad-file.md: missing 'name' in frontmatter"]
}
```

### Registration

Add in `src/swarm/mcp/forge_tools.py`.

---

## Tool 3: `artifact_list`

**Purpose:** Read artifacts.json and return all entries as a JSON array.

### MCP Tool Signature

```python
@mcp.tool()
def artifact_list(plan_dir: str = "") -> str:
```

### Directory Resolution

- If `plan_dir` non-empty → `Path(plan_dir) / "artifacts.json"`
- Else → `Path(state.plans_dir) / "artifacts.json"` if set, else `Path.cwd() / "artifacts.json"`

### Parsing Logic

```python
entries = []
for line in artifacts_file.read_text().splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        entries.append(json.loads(line))
    except json.JSONDecodeError:
        continue  # skip corrupt lines
```

### Edge Cases

- Missing file → return `"[]"`
- Corrupt lines → skip silently

### Return Format

```json
[
  {"agent_id": "abc-123", "path": "report.md", "description": "Final report"},
  {"agent_id": "", "path": "data.csv", "description": "Raw data"}
]
```

### Registration

Add in `src/swarm/mcp/artifact_tools.py`.

---

## Tool 4: `artifact_get`

**Purpose:** Read an artifact file's content plus its metadata from artifacts.json.

### MCP Tool Signature

```python
@mcp.tool()
def artifact_get(path: str, plan_dir: str = "", max_lines: str = "50") -> str:
```

Note: `max_lines` is string (MCP convention), parsed to int internally.

### Logic

1. Resolve artifacts.json location (same as `artifact_list`).
2. Scan artifacts.json for entry where `entry["path"] == path`. If found → metadata dict. If not → `null`.
3. Read the file at `path`. Try as-is first (handles absolute), then relative to `plan_dir` as fallback.
4. Take first `max_lines` lines.

### Return Format

```json
{
  "metadata": {"agent_id": "abc-123", "path": "report.md", "description": "Final report"},
  "content": "line 1\nline 2\n...",
  "truncated": true
}
```

- File not found: `{"metadata": ... | null, "content": null, "truncated": false, "error": "File not found: report.md"}`
- Path not in artifacts.json but file exists: `metadata` is `null`, content populated
- `truncated` is `true` when file has more lines than `max_lines`

### Registration

Add in `src/swarm/mcp/artifact_tools.py`.

---

## Tool 5: `swarm_discover`

**Purpose:** Lightweight catalog browsing — returns name + description + tags only, NEVER `system_prompt`. Progressive disclosure pattern.

### MCP Tool Signature

```python
@mcp.tool()
def swarm_discover(query: str = "") -> str:
```

### Logic

1. Empty query → `state.registry_api.list_agents()`
2. Non-empty query → `state.registry_api.search(query)`
3. Project each result to `{id, name, description, tags}` only — never include `system_prompt`

### Return Format

```json
[
  {"id": "...", "name": "code-reviewer", "description": "Reviews Python code", "tags": ["python", "review"]},
  {"id": "...", "name": "doc-writer", "description": "Writes documentation", "tags": ["docs"]}
]
```

### Registration

New file: `src/swarm/mcp/discovery_tools.py`
Import in `src/swarm/mcp/server.py` for side-effect registration.

---

## Affected Files

### Files to CREATE

| File | Purpose |
|---|---|
| `src/swarm/forge/frontmatter.py` | Minimal YAML frontmatter parser/renderer |
| `src/swarm/mcp/discovery_tools.py` | `swarm_discover` MCP tool |
| `tests/test_frontmatter.py` | Tests for frontmatter parser |
| `tests/test_mcp_discovery_tools.py` | Tests for `swarm_discover` |

### Files to MODIFY

| File | Changes |
|---|---|
| `src/swarm/mcp/forge_tools.py` | Add `forge_export_subagent`, `forge_import_subagents` |
| `src/swarm/mcp/artifact_tools.py` | Add `artifact_list`, `artifact_get` |
| `src/swarm/mcp/server.py` | Import `discovery_tools` for registration |
| `tests/test_mcp_forge_tools.py` | Tests for export/import |
| `tests/test_mcp_artifact_tools.py` | Tests for artifact_list/artifact_get |

### Files NOT modified

- `pyproject.toml` — no new dependencies
- `registry/models.py` — no model changes
- `registry/api.py` — uses existing methods
- `forge/api.py` — `create_agent` already has right signature
- `state.py` — no new globals

## Implementation Order

1. `src/swarm/forge/frontmatter.py` — zero dependencies, needed by both export and import
2. `src/swarm/mcp/artifact_tools.py` — self-contained, only needs state.plans_dir
3. `src/swarm/mcp/forge_tools.py` — add export (uses frontmatter renderer) and import (uses frontmatter parser)
4. `src/swarm/mcp/discovery_tools.py` + `server.py` — self-contained read-only tool
