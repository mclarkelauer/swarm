# Swarm examples

Runnable example plans built from base agents (no project-specific clones).
Each subdirectory contains a `plan.json` plus a README explaining what it
does, how to run it, and how to customize it.

| Example | What it shows | Pattern |
|---------|---------------|---------|
| [research/](research/) | Three parallel research tracks, checkpoint, single synthesis | fan-out -> checkpoint -> join |
| [code-review/](code-review/) | Linear analyze -> review -> summarize -> approve pipeline | sequential pipeline with artifacts |
| [incident-response/](incident-response/) | Triage, parallel log+code investigation, fix, postmortem | fan-out -> join -> sequential |

## Running any example

```bash
# Preview the DAG without spawning agents
swarm run examples/<name>/plan.json --dry-run

# Walk the DAG step by step
swarm run examples/<name>/plan.json
```

Every plan uses only agents from the base catalog (`swarm catalog list`),
so they should run on a fresh install without any forge work.

For the field-by-field reference on plan structure, see
[../docs/writing-plans.md](../docs/writing-plans.md).
