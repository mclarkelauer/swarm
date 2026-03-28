# Writing Plans

Plans are JSON files that define what a team of agents should accomplish. They describe a directed acyclic graph (DAG) of steps with dependencies. Claude Code uses these plans to coordinate agent execution.

## Plan Structure

```json
{
  "version": 1,
  "goal": "A clear description of the overall objective",
  "variables": {
    "key": "value"
  },
  "steps": [...]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `version` | integer | Plan version number (starts at 1) |
| `goal` | string | The objective this plan achieves |
| `variables` | object | Key-value pairs for template substitution in prompts |
| `steps` | array | Ordered list of plan steps |

## Step Types

Every step has these common fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Unique identifier for this step |
| `type` | string | yes | `"task"`, `"checkpoint"`, or `"loop"` |
| `prompt` | string | yes | Instructions for the agent or description of the checkpoint |
| `agent_type` | string | no | Name of the agent type to use (for tasks and loops) |
| `depends_on` | array | no | List of step IDs that must complete before this step runs |

### Task Steps

A task is a unit of work assigned to an agent. The agent is spawned, given the prompt, and runs to completion.

```json
{
  "id": "analyze-logs",
  "type": "task",
  "agent_type": "log-analyst",
  "prompt": "Analyze the error logs from the past week and identify the top 5 recurring issues.",
  "depends_on": ["collect-logs"]
}
```

The `agent_type` field matches against agent definitions in the registry. Use `forge_suggest` to find existing agents or `forge_create` to make new ones.

### Checkpoint Steps

A checkpoint pauses execution and waits for user input. Use these to review intermediate results before proceeding.

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

| checkpoint_config field | Type | Description |
|-------------------------|------|-------------|
| `message` | string | Message shown to the user at the checkpoint |

Execution pauses at a checkpoint until the user responds.

### Loop Steps

A loop runs an agent repeatedly until a termination condition is met.

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

| loop_config field | Type | Default | Description |
|-------------------|------|---------|-------------|
| `condition` | string | `""` | Human-readable termination condition |
| `max_iterations` | integer | `100000` | Safety net — loop stops after this many iterations regardless |

Loop termination fires on whichever comes first:

1. The plan-defined condition is met
2. The agent declares the loop complete
3. The coordinating agent judges the loop is done
4. The `max_iterations` safety net

## Variables and Template Substitution

Variables defined in the plan are substituted into step prompts at execution time. Use `{variable_name}` syntax:

```json
{
  "version": 1,
  "goal": "Audit the {service} codebase",
  "variables": {
    "service": "payment-api",
    "language": "Python"
  },
  "steps": [
    {
      "id": "scan",
      "type": "task",
      "agent_type": "security-scanner",
      "prompt": "Scan the {service} codebase ({language}) for security vulnerabilities"
    }
  ]
}
```

At execution, the prompt becomes: *"Scan the payment-api codebase (Python) for security vulnerabilities"*.

## DAG Dependencies

Steps run as soon as all their dependencies are satisfied. Steps with no dependencies (or empty `depends_on`) run immediately. Steps that share no dependency chains run in parallel.

### Parallel execution

Steps with no dependencies between them execute simultaneously:

```json
{
  "steps": [
    {"id": "research-a", "type": "task", "prompt": "...", "depends_on": []},
    {"id": "research-b", "type": "task", "prompt": "...", "depends_on": []},
    {"id": "research-c", "type": "task", "prompt": "...", "depends_on": []},
    {"id": "synthesize", "type": "task", "prompt": "...", "depends_on": ["research-a", "research-b", "research-c"]}
  ]
}
```

Here, `research-a`, `research-b`, and `research-c` all run in parallel. `synthesize` waits for all three to finish.

### Sequential pipeline

Chain steps for ordered execution:

```json
{
  "steps": [
    {"id": "collect",  "type": "task", "prompt": "...", "depends_on": []},
    {"id": "clean",    "type": "task", "prompt": "...", "depends_on": ["collect"]},
    {"id": "analyze",  "type": "task", "prompt": "...", "depends_on": ["clean"]},
    {"id": "report",   "type": "task", "prompt": "...", "depends_on": ["analyze"]}
  ]
}
```

### Fan-out / fan-in

Combine parallel and sequential patterns:

```json
{
  "steps": [
    {"id": "prepare",    "type": "task",       "prompt": "..."},
    {"id": "worker-1",   "type": "task",       "prompt": "...", "depends_on": ["prepare"]},
    {"id": "worker-2",   "type": "task",       "prompt": "...", "depends_on": ["prepare"]},
    {"id": "worker-3",   "type": "task",       "prompt": "...", "depends_on": ["prepare"]},
    {"id": "checkpoint",  "type": "checkpoint", "prompt": "Review parallel results",
     "depends_on": ["worker-1", "worker-2", "worker-3"]},
    {"id": "finalize",   "type": "task",       "prompt": "...", "depends_on": ["checkpoint"]}
  ]
}
```

## Versioning

Plans are immutable once saved. When a plan is modified, a new version is created:

```
plan_v1.json    # Original plan
plan_v2.json    # Modified during execution
plan_v3.json    # Further adjustments
```

The version number in the JSON increments with each save.

## Validation Rules

Plans are validated before execution. A valid plan must:

- Have a `version` >= 1
- Have a non-empty `goal`
- Have at least one step
- Have unique step IDs
- Have no circular dependencies (the DAG must be acyclic)
- Only reference existing step IDs in `depends_on`
- Have `loop_config` only on `"loop"` type steps
- Have `checkpoint_config` only on `"checkpoint"` type steps

## Complete Example

Here's the research example plan from `examples/research/plan.json`:

```json
{
  "version": 1,
  "goal": "Research LLMs and autonomous agents for engineering management",
  "variables": {
    "domain": "Linux kernel and operating system development",
    "role": "engineering manager",
    "output_format": "markdown"
  },
  "steps": [
    {
      "id": "research-llm-tools",
      "type": "task",
      "agent_type": "researcher",
      "prompt": "Research current LLM-based tools and agent frameworks for engineering management..."
    },
    {
      "id": "research-kernel-workflow",
      "type": "task",
      "agent_type": "researcher",
      "prompt": "Research the Linux kernel development workflow..."
    },
    {
      "id": "research-signals-patterns",
      "type": "task",
      "agent_type": "researcher",
      "prompt": "Research engineering manager signal detection patterns..."
    },
    {
      "id": "research-agent-architectures",
      "type": "task",
      "agent_type": "researcher",
      "prompt": "Research autonomous agent architectures for engineering management..."
    },
    {
      "id": "checkpoint-research",
      "type": "checkpoint",
      "prompt": "Review all research findings before synthesis",
      "depends_on": [
        "research-llm-tools",
        "research-kernel-workflow",
        "research-signals-patterns",
        "research-agent-architectures"
      ],
      "checkpoint_config": {
        "message": "All 4 research tracks complete. Review findings before generating the proposal."
      }
    },
    {
      "id": "synthesize-proposal",
      "type": "task",
      "agent_type": "synthesizer",
      "prompt": "Read ALL research findings and synthesize them into a comprehensive proposal...",
      "depends_on": ["checkpoint-research"]
    }
  ]
}
```

This plan runs 4 researchers in parallel, pauses for review, then runs a synthesizer. The DAG looks like:

```
research-llm-tools ──────────┐
research-kernel-workflow ─────┤
research-signals-patterns ────┼──> checkpoint-research ──> synthesize-proposal
research-agent-architectures ─┘
```
