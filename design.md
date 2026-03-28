# Swarm

Swarm is an MCP tool server and agent registry for multi-agent orchestration with Claude Code. It provides tools for designing specialized agents, managing a persistent agent catalog, and building DAG-based execution plans.

## Architecture

Claude Code is the orchestrator. Swarm extends it via MCP tools.

```
You <-> Claude Code <-> Swarm MCP Server
                            |
               ┌────────────┼────────────┐
               |            |            |
           Forge       Registry       Plan
        (create/clone  (SQLite DB)   (DAG/JSON)
         agents)
```

- `swarm` launches an interactive Claude Code session with MCP tools attached
- `swarm forge` launches a forge-focused session for designing agents
- CLI subcommands provide direct CRUD without a Claude session
- The MCP server runs as a subprocess managed by Claude Code

---

## Agent Forge

Agents are created on the fly to solve parts of the problem.

### ForgeAPI
- Query existing agent definitions with fuzzy search
- Clone-and-modify with provenance tracking
- Disk cache at `~/.swarm/forge/` for reusable definitions
- Source plugin system for external agent catalogs

### Agent Definitions (immutable)
- **name**: agent type name
- **system_prompt**: the agent's instructions
- **tools**: list of available tools (JSON array)
- **permissions**: list of permissions (JSON array)
- **working_dir**: workspace path
- **source**: where the definition came from (local, github, api, forge)
- **parent_id**: provenance — points to the definition this was cloned from (nullable)

Definitions are immutable. Modifications create clones with provenance chain.

### MCP Tools
- `forge_list(name_filter?)` — list all or filter by name
- `forge_get(agent_id?, name?)` — get by ID or name
- `forge_create(name, system_prompt, tools?, permissions?)` — create and register
- `forge_clone(source_id, name?, system_prompt?, tools?, permissions?)` — clone with overrides
- `forge_suggest(query)` — search registry + source plugins
- `forge_remove(agent_id)` — delete from registry

---

## Agent Registry

Persistent SQLite database at `~/.swarm/registry.db`.

### Schema
| Field | Type | Description |
|-------|------|-------------|
| id | TEXT PRIMARY KEY | UUID4 |
| name | TEXT | Agent type name |
| parent_id | TEXT (nullable) | FK to self for clone provenance |
| system_prompt | TEXT | Agent instructions |
| tools | TEXT | JSON array of tools |
| permissions | TEXT | JSON array of permissions |
| working_dir | TEXT | Workspace template |
| source | TEXT | Origin: local, github, api, forge |
| created_at | TEXT | ISO timestamp |

### Source Plugin System
Abstract `SourcePlugin` interface for external agent catalogs:
- `search(query)` — fuzzy search, returns matching definitions
- `install(name)` — exact lookup by name

Built-in: `LocalDirectorySource` scans a directory of JSON definition files.

### MCP Tools
- `registry_list()` — list all registered agents
- `registry_inspect(agent_id)` — full details + provenance chain
- `registry_search(query)` — search by name or prompt
- `registry_remove(agent_id)` — remove a definition

### CLI Commands
- `swarm registry list` — show all registered agents
- `swarm registry search <query>` — search by name or prompt
- `swarm registry inspect <id>` — show details + provenance chain
- `swarm registry create --name --prompt` — create new definition
- `swarm registry clone <id> --name` — clone with modifications
- `swarm registry remove <id>` — remove a definition

---

## Plan System

Plans are JSON files defining a DAG of tasks with dependencies, checkpoints, and loops.

### Plan JSON Structure
```json
{
  "version": 1,
  "goal": "The user's original goal",
  "variables": {"key": "value"},
  "steps": [
    {
      "id": "step-1",
      "type": "task",
      "agent_type": "researcher",
      "prompt": "Research {topic}",
      "depends_on": []
    },
    {
      "id": "step-2",
      "type": "checkpoint",
      "prompt": "Review results before proceeding",
      "depends_on": ["step-1"],
      "checkpoint_config": {"message": "Review results?"}
    },
    {
      "id": "step-3",
      "type": "loop",
      "agent_type": "iterator",
      "prompt": "Process next item",
      "depends_on": ["step-2"],
      "loop_config": {"condition": "all items processed", "max_iterations": 100000}
    }
  ]
}
```

### Step Types
- **task**: A unit of work assigned to an agent
- **checkpoint**: Pause for user feedback
- **loop**: Repeated execution with termination conditions

### Versioning
- Plans are immutable once saved
- Modifications create new versions: `plan_v1.json`, `plan_v2.json`, etc.
- Variable references `{variable_name}` in prompts resolved at execution time

### MCP Tools
- `plan_create(goal, steps_json, variables_json?, plans_dir?)` — validate and save
- `plan_validate(plan_json)` — validate without saving
- `plan_load(path)` — load from file
- `plan_list(plans_dir?)` — list versions in a directory
- `plan_get_ready_steps(plan_json, completed_json?)` — DAG-ready steps
- `plan_get_step(plan_json, step_id)` — single step details

### CLI Commands
- `swarm plan validate <file>` — validate a plan
- `swarm plan list [--dir .]` — list versions
- `swarm plan show <file>` — display plan structure

---

## MCP Server

The `swarm-mcp` server provides all tools to Claude Code sessions.

### Environment Variables
- `SWARM_BASE_DIR` — root Swarm directory (default: `~/.swarm`)
- `SWARM_PLANS_DIR` — directory for plan files (default: current working directory)

### Tools Summary
| Category | Tools |
|----------|-------|
| Forge | `forge_list`, `forge_get`, `forge_create`, `forge_clone`, `forge_suggest`, `forge_remove` |
| Plan | `plan_create`, `plan_validate`, `plan_load`, `plan_list`, `plan_get_ready_steps`, `plan_get_step` |
| Registry | `registry_list`, `registry_inspect`, `registry_search`, `registry_remove` |
| Artifacts | `artifact_declare` |

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
  config.json        # global configuration
  registry.db        # persistent agent registry
  forge/             # cached agent definitions
    {name}.json
  run/               # runtime files
    mcp_config.json  # MCP config for Claude sessions
```

Plans are stored in the project working directory as `plan_v{N}.json`.

---

## CLI

| Command | Description |
|---------|-------------|
| `swarm` | Launch interactive orchestrator Claude session |
| `swarm forge` | Launch interactive forge Claude session |
| `swarm forge design <task>` | One-shot agent design via Claude |
| `swarm forge suggest <query>` | Search for matching agents |
| `swarm plan validate <file>` | Validate a plan JSON file |
| `swarm plan list` | List plan versions |
| `swarm plan show <file>` | Display plan structure |
| `swarm registry list` | List registered agents |
| `swarm registry search <query>` | Search agents |
| `swarm registry create` | Create new agent definition |
| `swarm registry clone <id>` | Clone an agent |
| `swarm registry inspect <id>` | Agent details + provenance |
| `swarm registry remove <id>` | Remove an agent |
| `swarm mcp-config` | Print MCP config for Claude Code |
