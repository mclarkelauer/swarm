# Code-review example

A linear analyze -> review -> summarize -> approve pipeline. Each step
produces a markdown artifact that the next step consumes via
`required_inputs`, so there is a clear paper trail.

## Base agents used

- `code-analyzer` — static analysis pass
- `code-reviewer` — line-by-line review
- `technical-writer` — actionable summary

All three are in the base catalog. Clone if you want a project-specific
variant (e.g. `swarm catalog clone code-reviewer my-rust-reviewer`).

## Run it

```bash
# Preview
swarm run examples/code-review/plan.json --dry-run

# Walk the DAG
swarm run examples/code-review/plan.json
```

4 steps in 4 sequential waves — the pipeline is intentionally serial since
each step builds on the previous artifact.

## What success looks like

After running, the working directory will contain:

- `analysis.md` — structural analysis with line references
- `review.md` — full review with severity-tagged findings
- `summary.md` — actionable top-5 plus assessment
- `run_log.json` — execution record

## Customize

Set `variables.target` to scope the review:

```json
"variables": {
  "target": "the auth module under src/auth/",
  "project_dir": "/path/to/repo"
}
```

To add a critic loop on the review step, set `critic_agent: "critic"` and
`max_critic_iterations: 3` on the `review` step. See `docs/writing-plans.md`
for the full field reference.
