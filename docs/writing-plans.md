# Writing Plans

Plans are JSON files that define what a team of agents should accomplish.
They describe a directed acyclic graph (DAG) of steps with dependencies.
The Swarm executor walks the DAG, spawns agents, and produces a run log.

For the canonical schema see
[`src/swarm/plan/models.py`](../src/swarm/plan/models.py); for validation
rules see [`src/swarm/plan/parser.py`](../src/swarm/plan/parser.py).

## Plan structure

```json
{
  "version": 1,
  "goal": "A clear description of the overall objective",
  "variables": {"key": "value"},
  "max_replans": 5,
  "steps": [...]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | integer | yes | Plan version number (starts at 1; auto-bumped on `plan_amend`) |
| `goal` | string | yes | The objective this plan achieves |
| `variables` | object | no | Key-value pairs for `{name}` template substitution in step prompts |
| `steps` | array | yes | Ordered list of plan steps (must be non-empty) |
| `max_replans` | integer | no | Cap on dynamic replans during execution (default 5) |

## Step types

Seven step types are valid (see `_VALID_STEP_TYPES` in
[`parser.py`](../src/swarm/plan/parser.py)):

| Type | Purpose |
|------|---------|
| `task` | A single agent does a single unit of work |
| `checkpoint` | Pause for human review; no agent spawned |
| `loop` | Run an agent repeatedly until a termination condition |
| `fan_out` | Spawn N parallel branches, each with its own agent + prompt |
| `join` | Synchronization point that consumes the outputs of upstream steps |
| `decision` | Inline branch that activates / skips downstream steps based on conditions |
| `subplan` | Execute a nested plan from another JSON file as a single step |

## Common step fields

Every step has these fields. Sparse serialization — defaults are omitted
on `to_dict()`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | string | (required) | Unique identifier within the plan |
| `type` | string | (required) | One of the seven step types |
| `prompt` | string | `""` | Instructions for the agent (variables interpolated at execution) |
| `agent_type` | string | `""` | Agent name from the registry; required for `task` and `loop` |
| `depends_on` | array[string] | `[]` | Step IDs that must complete before this runs |
| `output_artifact` | string | `""` | File the step is expected to produce; consumed by downstream `required_inputs` |
| `required_inputs` | array[string] | `[]` | Files this step needs to read (artifacts produced upstream) |
| `on_failure` | string | `"stop"` | One of `stop`, `skip`, `retry` |
| `spawn_mode` | string | `"foreground"` | `foreground` blocks the wave; `background` lets the wave continue |
| `condition` | string | `""` | Conditional gate — see [Conditional gating](#conditional-gating) |
| `required_tools` | array[string] | `[]` | Tools the step needs; validated against the agent's tool list |
| `critic_agent` | string | `""` | If set, runs a critic loop (task steps only) |
| `max_critic_iterations` | integer | `3` | Max critic rounds per step |
| `message_to` | string | `""` | Auto-post the step output as a message to this agent |
| `timeout` | integer | `0` | Per-step timeout in seconds; `0` means no timeout |
| `retry_config` | object | `null` | Backoff policy when `on_failure: "retry"` |

Plus type-specific config blocks: `loop_config`, `checkpoint_config`,
`fan_out_config`, `decision_config`, `subplan_path`.

## Step type reference

### Task

A unit of work assigned to a single agent. The agent is spawned, given
the prompt, and runs to completion.

```json
{
  "id": "analyze-logs",
  "type": "task",
  "agent_type": "log-analyst",
  "prompt": "Analyze the error logs from the past week and identify the top 5 recurring issues.",
  "depends_on": ["collect-logs"],
  "output_artifact": "log-analysis.md"
}
```

`agent_type` is required for tasks. Use `forge_suggest_ranked` to find
existing agents or `forge_create` to make new ones.

### Checkpoint

Pauses execution and waits for user confirmation. No agent is spawned.

```json
{
  "id": "review-analysis",
  "type": "checkpoint",
  "prompt": "Review the log analysis before generating recommendations",
  "depends_on": ["analyze-logs"],
  "checkpoint_config": {
    "message": "Log analysis complete. Review findings before proceeding?"
  }
}
```

| `checkpoint_config` field | Type | Description |
|---------------------------|------|-------------|
| `message` | string | Prompt shown to the user at the checkpoint |

### Loop

Run an agent repeatedly until a termination condition fires.

```json
{
  "id": "process-items",
  "type": "loop",
  "agent_type": "item-processor",
  "prompt": "Process the next unprocessed item from the queue",
  "depends_on": ["load-queue"],
  "loop_config": {
    "condition": "all items processed",
    "max_iterations": 500
  }
}
```

| `loop_config` field | Type | Default | Description |
|---------------------|------|---------|-------------|
| `condition` | string | `""` | Human-readable termination condition |
| `max_iterations` | integer | `10` | Safety net |

Termination fires on whichever comes first: the plan-defined condition is
met, the agent declares completion, the orchestrator judges the loop
done, or `max_iterations` is hit. Loop semantics are inverted: the loop
*continues* while the condition is False and *terminates* when True.

### Fan-out

Spawn N branches in parallel, each with its own agent and prompt.
Branches share the parent step's `id` and dependencies; each branch can
declare its own `output_artifact`.

```json
{
  "id": "research",
  "type": "fan_out",
  "prompt": "Research {topic} from multiple perspectives",
  "fan_out_config": {
    "branches": [
      {
        "agent_type": "technical-researcher",
        "prompt": "Technical landscape for {topic}",
        "output_artifact": "technical-research.md"
      },
      {
        "agent_type": "market-researcher",
        "prompt": "Market landscape for {topic}",
        "output_artifact": "market-research.md"
      }
    ]
  }
}
```

| `fan_out_config.branches[]` field | Type | Description |
|-----------------------------------|------|-------------|
| `agent_type` | string | Agent for this branch |
| `prompt` | string | Branch-specific prompt |
| `output_artifact` | string | Artifact this branch produces |

### Join

Synchronization step. Waits for upstream branches and produces a
consolidated output.

```json
{
  "id": "synthesize",
  "type": "join",
  "agent_type": "technical-writer",
  "prompt": "Synthesize the research from technical-research.md and market-research.md.",
  "depends_on": ["research"],
  "required_inputs": ["technical-research.md", "market-research.md"],
  "output_artifact": "synthesis.md"
}
```

`join` requires `depends_on` to be non-empty (validated). Functionally
similar to a `task` whose dependencies are upstream branches, with the
semantic intent made explicit.

### Decision

Inline branch — no agent spawned. Evaluates each action's condition and
activates / skips downstream steps via `ConditionalAction`.

```json
{
  "id": "should-deploy",
  "type": "decision",
  "prompt": "Decide whether to deploy based on test results",
  "depends_on": ["run-tests"],
  "decision_config": {
    "actions": [
      {
        "condition": "step_completed:run-tests",
        "activate_steps": ["deploy"],
        "skip_steps": ["rollback"]
      },
      {
        "condition": "step_failed:run-tests",
        "activate_steps": ["rollback"],
        "skip_steps": ["deploy"]
      }
    ]
  }
}
```

`activate_steps` and `skip_steps` reference other step IDs (validated).
Decisions execute inline, so they're cheap.

### Subplan

Execute a nested plan from another file as a single step.

```json
{
  "id": "run-incident-pipeline",
  "type": "subplan",
  "prompt": "Run the incident response sub-plan",
  "subplan_path": "examples/incident-response/plan.json",
  "depends_on": ["triage"]
}
```

The nested plan runs in the same run context (same `run_id`, shared
context, shared message bus).

## Conditional gating

The `condition` field on any step gates execution. Valid expressions
(see [`src/swarm/plan/conditions.py`](../src/swarm/plan/conditions.py)):

| Expression | Meaning |
|------------|---------|
| `""` or `"always"` | Always execute (default) |
| `"never"` | Always skip |
| `"artifact_exists:<path>"` | Run only if the file exists in the artifacts dir |
| `"step_completed:<step_id>"` | Run only if the named step completed |
| `"step_failed:<step_id>"` | Run only if the named step failed |
| `"iteration_ge:<N>"` | (Loops) run only at iteration N or later |
| `"output_contains:<step_id>:<regex>"` | Run only if the named step's stdout matches the regex |

```json
{
  "id": "deep-dive",
  "type": "task",
  "agent_type": "security-auditor",
  "prompt": "Investigate critical findings from analysis",
  "depends_on": ["analyze"],
  "condition": "artifact_exists:critical-findings.md",
  "required_inputs": ["critical-findings.md"]
}
```

Unknown conditions are permissive at evaluation time but fail validation
at parse time, so typos surface early.

## Critic loops

Set `critic_agent` on a `task` step to gate its output behind a critic.
The critic accepts or rejects; on reject, the original agent revises;
loop terminates on accept or after `max_critic_iterations` rounds
(default 3).

```json
{
  "id": "refine",
  "type": "task",
  "agent_type": "technical-writer",
  "prompt": "Improve the draft at draft.md based on critic feedback",
  "depends_on": ["draft"],
  "required_inputs": ["draft.md"],
  "output_artifact": "refined.md",
  "critic_agent": "code-reviewer",
  "max_critic_iterations": 3
}
```

Validation: `critic_agent` is only valid on `task` steps;
`max_critic_iterations` >= 1; setting `max_critic_iterations` without
`critic_agent` is a warning.

## Retry policies

Set `on_failure: "retry"` and (optionally) `retry_config` for exponential
backoff:

```json
{
  "id": "flaky-api-call",
  "type": "task",
  "agent_type": "api-caller",
  "prompt": "Call the upstream API",
  "on_failure": "retry",
  "retry_config": {
    "max_retries": 5,
    "backoff_seconds": 1.0,
    "backoff_multiplier": 2.0,
    "max_backoff_seconds": 30.0
  }
}
```

Delay formula: `delay = backoff_seconds * (backoff_multiplier ^ attempt)`,
capped at `max_backoff_seconds`. Defaults: 3 retries, 2s base, 2x
multiplier, 60s cap. Validation requires `on_failure: "retry"` whenever
`retry_config` is set, and all numeric fields > 0.

## Timeouts

Per-step timeout in seconds. `0` (default) means no timeout. The executor
sends SIGTERM at the deadline.

```json
{
  "id": "lengthy-research",
  "type": "task",
  "agent_type": "online-researcher",
  "prompt": "Deep research on {topic}",
  "timeout": 1800
}
```

## Spawn mode

| `spawn_mode` | Meaning |
|--------------|---------|
| `"foreground"` (default) | Wave waits for this step to finish |
| `"background"` | Wave continues; step runs detached and is reaped on completion |

Background steps must still satisfy their own `depends_on` before they
launch.

## Variables and template substitution

Variables defined in the plan are substituted into step prompts at
execution time using `{name}` syntax:

```json
{
  "version": 1,
  "goal": "Audit the {service} codebase",
  "variables": {"service": "payment-api", "language": "Python"},
  "steps": [
    {
      "id": "scan",
      "type": "task",
      "agent_type": "security-auditor",
      "prompt": "Scan the {service} codebase ({language}) for security vulnerabilities"
    }
  ]
}
```

The prompt becomes: *"Scan the payment-api codebase (Python) for security
vulnerabilities"*. Unknown placeholders are left intact (safe regex
substitution).

## DAG dependencies

Steps run as soon as all their `depends_on` are satisfied. Empty
`depends_on` (or omitting it) means run immediately. Steps that share no
dependency chains run in parallel — call this a *wave*.

### Parallel execution

```json
{
  "steps": [
    {"id": "research-a", "type": "task", "prompt": "...", "depends_on": []},
    {"id": "research-b", "type": "task", "prompt": "...", "depends_on": []},
    {"id": "research-c", "type": "task", "prompt": "...", "depends_on": []},
    {"id": "synthesize", "type": "task", "prompt": "...",
     "depends_on": ["research-a", "research-b", "research-c"]}
  ]
}
```

Three researchers run in parallel; `synthesize` waits for all three.

### Sequential pipeline

```json
{
  "steps": [
    {"id": "collect", "type": "task", "prompt": "..."},
    {"id": "clean",   "type": "task", "prompt": "...", "depends_on": ["collect"]},
    {"id": "analyze", "type": "task", "prompt": "...", "depends_on": ["clean"]},
    {"id": "report",  "type": "task", "prompt": "...", "depends_on": ["analyze"]}
  ]
}
```

### Fan-out / fan-in

```json
{
  "steps": [
    {"id": "prepare",  "type": "task", "prompt": "..."},
    {"id": "worker-1", "type": "task", "prompt": "...", "depends_on": ["prepare"]},
    {"id": "worker-2", "type": "task", "prompt": "...", "depends_on": ["prepare"]},
    {"id": "worker-3", "type": "task", "prompt": "...", "depends_on": ["prepare"]},
    {"id": "review", "type": "checkpoint", "prompt": "Review parallel results",
     "depends_on": ["worker-1", "worker-2", "worker-3"]},
    {"id": "finalize", "type": "task", "prompt": "...", "depends_on": ["review"]}
  ]
}
```

You can also use the dedicated `fan_out` step type for a more compact
representation when each branch is just an agent + prompt + artifact.

## Inter-agent messaging from a step

The `message_to` field auto-posts the step's output as an
`AgentMessage` addressed to the named agent in the run-scoped bus:

```json
{
  "id": "investigate",
  "type": "task",
  "agent_type": "security-auditor",
  "prompt": "Investigate the alert",
  "message_to": "incident-responder"
}
```

See [messaging.md](messaging.md) for the messaging API reference.

## Versioning

Plans are immutable once saved. Modifications create a new version:

```
plan_v1.json   # original
plan_v2.json   # after first amendment
plan_v3.json   # ...
```

`plan_amend` MCP tool bumps the version and writes a new file.
`swarm run --latest` picks the highest-numbered version in the directory.

## Validation rules

A valid plan satisfies all of:

- `version` >= 1
- non-empty `goal`
- at least one step
- unique step IDs
- no circular dependencies (DAG must be acyclic)
- only references existing step IDs in `depends_on`,
  `decision_config.actions[*].activate_steps`, and `skip_steps`
- step `type` in `{task, checkpoint, loop, fan_out, join, decision, subplan}`
- `task` steps have `agent_type`
- `loop` steps have `loop_config`
- `fan_out` steps have `fan_out_config` with at least one branch
- `decision` steps have `decision_config`
- `join` steps have non-empty `depends_on`
- `on_failure` in `{stop, skip, retry}`
- `spawn_mode` in `{foreground, background}`
- non-empty strings in `required_inputs`
- valid `condition` expression
- `critic_agent` only on task steps; `max_critic_iterations` >= 1
- `retry_config` only when `on_failure: "retry"`; all retry fields > 0

Run validation up-front via `swarm run plan.json --dry-run` (which loads,
validates, and prints the wave table without spawning anything).

## Complete example

The minimal research plan from
[`examples/research/plan.json`](../examples/research/plan.json):

```json
{
  "version": 1,
  "goal": "Research {topic} from multiple angles and produce a synthesized report",
  "variables": {
    "topic": "open-source vector databases",
    "output_format": "markdown"
  },
  "steps": [
    {
      "id": "research-landscape",
      "type": "task",
      "agent_type": "online-researcher",
      "prompt": "Survey the current landscape of {topic}...",
      "output_artifact": "landscape.md"
    },
    {
      "id": "research-tradeoffs",
      "type": "task",
      "agent_type": "online-researcher",
      "prompt": "Analyze technical trade-offs for {topic}...",
      "output_artifact": "tradeoffs.md"
    },
    {
      "id": "research-adoption",
      "type": "task",
      "agent_type": "online-researcher",
      "prompt": "Document real-world adoption of {topic}...",
      "output_artifact": "adoption.md"
    },
    {
      "id": "review",
      "type": "checkpoint",
      "prompt": "Review the three research tracks before synthesis",
      "depends_on": ["research-landscape", "research-tradeoffs", "research-adoption"],
      "checkpoint_config": {"message": "All three research tracks complete..."}
    },
    {
      "id": "synthesize",
      "type": "task",
      "agent_type": "summarizer",
      "prompt": "Read all three reports and produce a single synthesis",
      "depends_on": ["review"],
      "required_inputs": ["landscape.md", "tradeoffs.md", "adoption.md"],
      "output_artifact": "synthesis.md"
    }
  ]
}
```

The DAG:

```
research-landscape ─┐
research-tradeoffs ─┼─> review (checkpoint) ─> synthesize
research-adoption  ─┘
```

See [`examples/`](../examples/) for two more runnable scenarios
(`code-review`, `incident-response`).
