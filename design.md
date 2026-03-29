# Swarm

Swarm is an MCP tool server and agent registry for multi-agent orchestration with Claude Code. It provides 30 MCP tools for designing specialized agents, managing a persistent agent catalog, building DAG-based execution plans, and closing the feedback loop — all accessible inside a Claude Code session.

## Architecture

Claude Code is the orchestrator. Swarm extends it via MCP tools.

```
You <-> Claude Code <-> Swarm MCP Server (30 tools)
                            |
               ┌────────────┼────────────┐────────────┐
               |            |            |            |
           Forge       Registry       Plan       Artifacts
        (create/clone  (SQLite DB)   (DAG/JSON)  (declare/query)
         export/import               templates
         annotate)                   amend/patch
```

- `swarm` launches an interactive Claude Code session with MCP tools attached
- `swarm forge` launches a forge-focused session for designing agents
- CLI subcommands provide direct CRUD without a Claude session
- The MCP server runs as a subprocess managed by Claude Code

---

## Agent Forge

Agents are created on the fly to solve parts of the problem.

### ForgeAPI
- Query existing agent definitions with fuzzy search and semantic re-ranking
- Clone-and-modify with provenance tracking
- Disk cache at `~/.swarm/forge/` for reusable definitions
- Source plugin system for external agent catalogs
- Export/import bridge to Claude Code's native `.claude/agents/` format
- Performance annotation from run logs (feedback loop)

### Agent Definitions (immutable)
| Field | Type | Description |
|-------|------|-------------|
| **name** | str | Agent type name |
| **description** | str | One-sentence summary for discovery |
| **system_prompt** | str | Full instructions for the agent |
| **tools** | list | Available tools |
| **permissions** | list | Required permissions |
| **tags** | list | Categorical labels for filtering |
| **notes** | str | Lessons learned, behavioral guidance |
| **usage_count** | int | Total times used across runs |
| **failure_count** | int | Total failures across runs |
| **last_used** | str | ISO timestamp of last use |
| **working_dir** | str | Workspace path |
| **source** | str | Origin: forge, project, local |
| **parent_id** | str? | Provenance — cloned from (nullable) |

Definitions are immutable. Modifications create clones with provenance chain. Clone resets usage/failure counts but preserves notes.

### MCP Tools
- `forge_list(name_filter?)` — list all (system_prompt truncated to 80 chars)
- `forge_get(agent_id?, name?)` — full definition by ID or name
- `forge_create(name, system_prompt, tools?, permissions?, description?, tags?, notes?)` — create and register
- `forge_clone(source_id, name?, system_prompt?, ...)` — clone with overrides
- `forge_suggest(query)` — search registry + source plugins
- `forge_suggest_ranked(query)` — search + LLM re-ranking prompt
- `forge_remove(agent_id)` — delete from registry
- `forge_export_subagent(agent_id?, name?, output_dir?)` — write `.claude/agents/<name>.md`
- `forge_import_subagents(project_dir?)` — import `.claude/agents/*.md` into registry
- `forge_annotate_from_run(run_log_path, plan_path?)` — update agents from run outcomes

### Discovery
- `swarm_discover(query?)` — lightweight browsing: name + description + tags + usage stats (never system_prompt)

---

## Agent Registry

Persistent SQLite database at `~/.swarm/registry.db`.

### Schema
| Field | Type | Description |
|-------|------|-------------|
| id | TEXT PK | UUID4 |
| name | TEXT | Agent type name |
| description | TEXT | One-sentence summary |
| parent_id | TEXT? | FK to self for clone provenance |
| system_prompt | TEXT | Agent instructions |
| tools | TEXT | JSON array of tools |
| permissions | TEXT | JSON array of permissions |
| tags | TEXT | JSON array of tags |
| notes | TEXT | Lessons learned |
| usage_count | INTEGER | Total uses |
| failure_count | INTEGER | Total failures |
| last_used | TEXT | ISO timestamp |
| working_dir | TEXT | Workspace template |
| source | TEXT | Origin: forge, project, local |
| created_at | TEXT | ISO timestamp |

Schema is auto-migrated: new columns are added idempotently via `ALTER TABLE` on existing databases.

### Source Plugin System
Abstract `SourcePlugin` interface for external agent catalogs:
- `search(query)` — fuzzy search, returns matching definitions
- `install(name)` — exact lookup by name

Built-in: `LocalDirectorySource` (scans JSON files), `ProjectDirectorySource` (scans `.swarm/agents/*.agent.json`).

### MCP Tools
- `registry_list()` — list all registered agents
- `registry_inspect(agent_id)` — full details + provenance chain
- `registry_search(query)` — search by name, description, or tags
- `registry_remove(agent_id)` — remove a definition

---

## Plan System

Plans are JSON files defining a DAG of tasks with dependencies, checkpoints, conditions, and parallel execution.

### Step Types
| Type | Description |
|------|-------------|
| **task** | A unit of work assigned to an agent. Supports `critic_agent` for quality review loops. |
| **checkpoint** | Pause for user feedback. |
| **loop** | Repeated execution with termination conditions. |
| **fan_out** | Spawn multiple agents in parallel (requires `fan_out_config`). |
| **join** | Collect results from parallel branches. |

### Step Fields
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| id | str | required | Unique step identifier |
| type | str | required | Step type (task/checkpoint/loop/fan_out/join) |
| prompt | str | required | Step prompt (supports `{var}` interpolation) |
| agent_type | str | "" | Agent to execute this step |
| depends_on | list | [] | Step IDs this depends on |
| output_artifact | str | "" | File path this step produces |
| required_inputs | list | [] | Artifact paths that must exist first |
| on_failure | str | "stop" | Failure strategy: stop, skip, retry |
| spawn_mode | str | "foreground" | foreground or background |
| condition | str | "" | Gating: always, never, artifact_exists:, step_completed:, step_failed: |
| critic_agent | str | "" | Agent that reviews output (task steps only) |
| max_critic_iterations | int | 3 | Max review cycles before accepting |
| required_tools | list | [] | Tools this step needs (validated against agent) |
| fan_out_config | object? | null | Branches for fan_out steps |

### Templates
Built-in templates at `src/swarm/plan/builtin_templates/`:
- `code-review` — analyze, review, summarize, approve
- `feature-build` — design, approve, implement, test, review, approve
- `security-audit` — scan, analyze, report, review, approve

User templates in `~/.swarm/templates/` override built-ins on name collision.

### Versioning
- Plans are immutable once saved
- Modifications create new versions: `plan_v1.json`, `plan_v2.json`, etc.
- `plan_amend` splices new steps mid-plan with dependency rewiring
- `plan_patch_step` updates a single step without changing DAG structure

### MCP Tools
- `plan_template_list()` — list available templates
- `plan_template_instantiate(name, variables_json?)` — instantiate a template
- `plan_create(goal, steps_json, variables_json?, plans_dir?)` — validate and save
- `plan_validate(plan_json)` — validate without saving
- `plan_validate_policies(plan_path)` — check tool policies against registry
- `plan_amend(plan_path, insert_after, new_steps_json)` — splice steps mid-plan
- `plan_patch_step(plan_path, step_id, overrides_json)` — update a single step
- `plan_load(path)` — load from file
- `plan_list(plans_dir?)` — list versions in a directory
- `plan_execute_step(plan_path, step_id, variables_json?)` — resolve agent + build invocation payload
- `plan_get_ready_steps(plan_json, completed_json?, artifacts_dir?, step_outcomes_json?)` — DAG-ready steps
- `plan_get_step(plan_json, step_id)` — single step details
- `plan_retrospective(run_log_path, plan_path?)` — post-run analysis with suggestions

### Artifact Tools
- `artifact_declare(path, description, agent_id?)` — declare a step output
- `artifact_list(plan_dir?)` — list all declared artifacts
- `artifact_get(path, plan_dir?, max_lines?)` — read content + metadata

---

## MCP Server

The `swarm-mcp` server provides all 30 tools to Claude Code sessions.

### Environment Variables
- `SWARM_BASE_DIR` — root Swarm directory (default: `~/.swarm`)
- `SWARM_PLANS_DIR` — directory for plan files (default: current working directory)

### Tools Summary (30 tools)
| Category | Tools |
|----------|-------|
| Discovery | `swarm_discover` |
| Forge | `forge_list`, `forge_get`, `forge_create`, `forge_clone`, `forge_suggest`, `forge_suggest_ranked`, `forge_remove`, `forge_export_subagent`, `forge_import_subagents`, `forge_annotate_from_run` |
| Plan | `plan_template_list`, `plan_template_instantiate`, `plan_create`, `plan_validate`, `plan_validate_policies`, `plan_amend`, `plan_patch_step`, `plan_load`, `plan_list`, `plan_execute_step`, `plan_get_ready_steps`, `plan_get_step`, `plan_retrospective` |
| Registry | `registry_list`, `registry_inspect`, `registry_search`, `registry_remove` |
| Artifacts | `artifact_declare`, `artifact_list`, `artifact_get` |

---

## Configuration

Single file: `~/.swarm/config.json`

| Key | Default | Description |
|-----|---------|-------------|
| base_dir | ~/.swarm | Root directory for all Swarm data |
| forge_timeout | 600 | Seconds before forge design times out |

---

## Directory Structure

```
~/.swarm/
  config.json           # global configuration
  registry.db           # persistent agent registry
  forge/                # cached agent definitions
    {name}.json
  templates/            # user plan templates (override built-ins)
  run/                  # runtime files
    mcp_config.json     # MCP config for Claude sessions

<project>/
  plan_v{N}.json        # plan versions
  run_log.json          # execution log
  artifacts.json        # declared artifacts
  .swarm/agents/        # project-local agent definitions
```

---

## CLI

| Command | Description |
|---------|-------------|
| `swarm` | Launch interactive orchestrator Claude session |
| `swarm ls` | Show agents and plans in current directory |
| `swarm forge` | Launch interactive forge Claude session |
| `swarm forge design <task>` | One-shot agent design via Claude |
| `swarm forge suggest <query>` | Search for matching agents |
| `swarm forge edit <name>` | Edit agent prompt in $EDITOR (creates clone) |
| `swarm forge export <name>` | Export to .agent.json file |
| `swarm forge import <file>` | Import from .agent.json file |
| `swarm plan validate <file>` | Validate a plan JSON file |
| `swarm plan list` | List plan versions |
| `swarm plan show <file>` | Display plan structure |
| `swarm run <file>` | Walk a plan's DAG interactively |
| `swarm run --latest` | Auto-pick highest version plan |
| `swarm run --dry-run` | Preview execution waves without running |
| `swarm status` | Show run progress from run_log.json |
| `swarm status --diagnose` | Failure analysis with suggested fixes |
| `swarm registry list` | List registered agents |
| `swarm registry search <query>` | Search by name, description, tags |
| `swarm registry inspect <id>` | Agent details + provenance |
| `swarm registry create` | Create new agent definition |
| `swarm registry clone <id>` | Clone an agent |
| `swarm registry remove <id>` | Remove an agent |
| `swarm sync` | Import .swarm/agents/ into registry |
| `swarm mcp-config` | Print MCP config for Claude Code |
