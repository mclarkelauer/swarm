# Research example

A parallel-research workflow: three online researchers investigate a topic from
different angles, a checkpoint pauses for human review, then a summarizer
produces a single synthesized report.

## Base agents used

- `online-researcher` (x3, fan-out) — landscape, trade-offs, adoption tracks
- `summarizer` — final synthesis

All agents ship in the base catalog (`swarm catalog list`). No project-specific
clones required.

## Run it

```bash
# Preview the wave plan without spawning agents
swarm run examples/research/plan.json --dry-run

# Walk the DAG interactively
swarm run examples/research/plan.json
```

The plan contains 5 steps in 3 waves: 3 parallel researchers, then a
checkpoint, then the synthesis.

## What success looks like

After running, the working directory will contain:

- `landscape.md`, `tradeoffs.md`, `adoption.md` — the three research outputs
- `synthesis.md` — the final synthesized report
- `run_log.json` — execution record (start/finish times per step)

## Customize

Edit `variables.topic` in `plan.json` to point at any subject:

```json
"variables": {
  "topic": "Rust async runtimes",
  "output_format": "markdown"
}
```

Add or remove research tracks by editing the `research-*` steps and updating
the `synthesize` step's `required_inputs` to match.
