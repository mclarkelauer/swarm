# Incident-response example

A fan-out incident pipeline: triage, two parallel investigations (logs and
code), then a synthesized fix and postmortem. Mirrors the built-in
`incident-response` template but uses only base agents.

## Base agents used

- `incident-responder` — initial triage
- `code-analyzer` — log investigation track
- `code-reviewer` — code investigation track
- `implementer` — applies the fix
- `technical-writer` — postmortem

All five ship in the base catalog.

## Run it

```bash
# Preview
swarm run examples/incident-response/plan.json --dry-run

# Walk the DAG
swarm run examples/incident-response/plan.json
```

5 steps in 4 waves. The two investigations run in parallel after triage,
then `fix` joins them, then the postmortem closes out the run.

## What success looks like

After running, the working directory will contain:

- `triage.md` — initial scope, severity, containment
- `log-investigation.md` and `code-investigation.md` — parallel root-cause work
- `fix.md` — the change shipped, plus rollback plan
- `postmortem.md` — blameless writeup
- `run_log.json` — execution record

## Customize

Drop in your real incident details:

```json
"variables": {
  "incident_description": "auth tokens expiring after 60s instead of 1h",
  "service": "auth-service",
  "severity": "critical"
}
```

For higher-stakes incidents, add `critic_agent: "critic"` to the `fix` step
to gate the change behind a review loop, or add a `checkpoint` step after
`fix` to require human approval before postmortem. See
`docs/writing-plans.md` for the full step-field reference.
