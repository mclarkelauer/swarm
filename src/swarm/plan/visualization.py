"""Plan DAG visualization: Mermaid flowcharts and ASCII wave tables."""

from __future__ import annotations

from swarm.plan.dag import topological_sort
from swarm.plan.models import Plan, PlanStep


def _step_status(
    step: PlanStep,
    completed: set[str],
    step_outcomes: dict[str, str],
) -> str:
    """Determine the display status of a step.

    Returns one of: ``"completed"``, ``"failed"``, ``"ready"``,
    ``"checkpoint"``, or ``"blocked"``.
    """
    if step.id in step_outcomes and step_outcomes[step.id] == "failed":
        return "failed"
    if step.id in completed:
        return "completed"
    if step.type == "checkpoint" and step.id not in completed:
        # Checkpoint steps that haven't run yet get special styling when all
        # dependencies are met.
        all_deps_met = all(d in completed for d in step.depends_on)
        if all_deps_met:
            return "checkpoint"
        return "blocked"
    # Check if all dependencies are satisfied.
    all_deps_met = all(d in completed for d in step.depends_on)
    if all_deps_met:
        return "ready"
    return "blocked"


def _sanitize_id(step_id: str) -> str:
    """Sanitize a step ID for use as a Mermaid node identifier.

    Replaces characters that are invalid in Mermaid identifiers with
    underscores.
    """
    return step_id.replace("-", "_").replace(".", "_").replace(" ", "_")


def _escape_label(text: str) -> str:
    """Escape characters that are special in Mermaid labels."""
    return text.replace('"', "'")


def render_mermaid(
    plan: Plan,
    completed: set[str] | None = None,
    step_outcomes: dict[str, str] | None = None,
) -> str:
    """Generate a Mermaid flowchart diagram from a Plan.

    Nodes are labeled with step ID and ``agent_type``.  Edges are derived from
    ``depends_on`` relationships.  Steps are color-coded by status:

    - **green** -- completed
    - **red** -- failed
    - **yellow** -- ready (dependencies met, not yet executed)
    - **gray** -- blocked (dependencies not yet met)
    - **blue** -- checkpoint (a checkpoint step whose deps are met)

    Fan-out branches are rendered as parallel paths from the fan-out node.
    Condition labels appear on edges when the target step has a non-empty
    ``condition``.  Steps with a ``critic_agent`` are annotated with a cycle
    arrow note.

    Args:
        plan: The execution plan to visualize.
        completed: Set of step IDs that have completed.  ``None`` is treated
            as an empty set.
        step_outcomes: Mapping of step ID to outcome string (e.g.
            ``"failed"``).  ``None`` is treated as an empty dict.

    Returns:
        A Mermaid flowchart string (``flowchart TD`` orientation).
    """
    completed = completed or set()
    step_outcomes = step_outcomes or {}

    style_map: dict[str, str] = {
        "completed": "fill:#28a745,stroke:#1e7e34,color:#fff",
        "failed": "fill:#dc3545,stroke:#bd2130,color:#fff",
        "ready": "fill:#ffc107,stroke:#d39e00,color:#000",
        "blocked": "fill:#6c757d,stroke:#545b62,color:#fff",
        "checkpoint": "fill:#007bff,stroke:#0062cc,color:#fff",
    }

    lines: list[str] = ["flowchart TD"]

    # --- Nodes ---
    for step in plan.steps:
        sid = _sanitize_id(step.id)
        label_parts = [step.id]
        if step.agent_type:
            label_parts.append(step.agent_type)
        label = _escape_label(" | ".join(label_parts))
        lines.append(f'    {sid}["{label}"]')

    # --- Fan-out sub-nodes ---
    # For fan_out steps, create sub-nodes for each branch and connect them.
    fan_out_branch_ids: dict[str, list[str]] = {}
    for step in plan.steps:
        if step.fan_out_config is not None and step.fan_out_config.branches:
            branch_ids: list[str] = []
            for idx, branch in enumerate(step.fan_out_config.branches):
                branch_id = f"{_sanitize_id(step.id)}_b{idx}"
                branch_label = _escape_label(
                    f"{step.id}/b{idx} | {branch.agent_type}"
                )
                lines.append(f'    {branch_id}["{branch_label}"]')
                branch_ids.append(branch_id)
            fan_out_branch_ids[step.id] = branch_ids

    # --- Edges ---
    for step in plan.steps:
        sid = _sanitize_id(step.id)
        for dep_id in step.depends_on:
            dep_sid = _sanitize_id(dep_id)
            if step.condition:
                cond_label = _escape_label(step.condition)
                lines.append(f"    {dep_sid} -->|{cond_label}| {sid}")
            else:
                lines.append(f"    {dep_sid} --> {sid}")

    # Fan-out edges: fan_out node -> each branch sub-node
    for step_id, branch_ids in fan_out_branch_ids.items():
        parent_sid = _sanitize_id(step_id)
        for branch_id in branch_ids:
            lines.append(f"    {parent_sid} --> {branch_id}")

    # --- Critic loop annotations ---
    for step in plan.steps:
        if step.critic_agent:
            sid = _sanitize_id(step.id)
            lines.append(
                f"    {sid} -. critic: {_escape_label(step.critic_agent)} .-> {sid}"
            )

    # --- Style classes ---
    for step in plan.steps:
        sid = _sanitize_id(step.id)
        status = _step_status(step, completed, step_outcomes)
        style = style_map[status]
        lines.append(f"    style {sid} {style}")

    # Style fan-out branch sub-nodes as blocked by default (they are
    # informational nodes, not directly tracked in completed).
    for branch_ids in fan_out_branch_ids.values():
        for branch_id in branch_ids:
            lines.append(f"    style {branch_id} {style_map['blocked']}")

    return "\n".join(lines)


def _compute_waves(plan: Plan) -> list[list[PlanStep]]:
    """Group plan steps into parallel execution waves via topological sort.

    Each wave contains steps that can run in parallel -- i.e., all of their
    dependencies are satisfied by steps in earlier waves.
    """
    sorted_steps = topological_sort(plan)
    # Map each step to the earliest wave it can appear in.
    wave_of: dict[str, int] = {}
    for step in sorted_steps:
        if not step.depends_on:
            wave_of[step.id] = 0
        else:
            wave_of[step.id] = max(wave_of.get(d, 0) for d in step.depends_on) + 1

    # Group by wave number.
    max_wave = max(wave_of.values()) if wave_of else 0
    waves: list[list[PlanStep]] = [[] for _ in range(max_wave + 1)]
    for step in sorted_steps:
        waves[wave_of[step.id]].append(step)
    return waves


def render_ascii(
    plan: Plan,
    completed: set[str] | None = None,
    step_outcomes: dict[str, str] | None = None,
) -> str:
    """Generate a simple ASCII table showing execution waves.

    Steps are grouped into waves (parallel groups derived from topological
    sort).  Dependencies are shown inline and status is indicated by symbols:

    - ``[checkmark]`` completed
    - ``[x]`` failed
    - ``[arrow]`` ready
    - ``[dot]`` blocked

    Args:
        plan: The execution plan to visualize.
        completed: Set of step IDs that have completed.
        step_outcomes: Mapping of step ID to outcome string.

    Returns:
        A multi-line ASCII string.
    """
    completed = completed or set()
    step_outcomes = step_outcomes or {}

    status_symbols: dict[str, str] = {
        "completed": "\u2713",
        "failed": "\u2717",
        "ready": "\u2192",
        "blocked": "\u00b7",
        "checkpoint": "\u2192",
    }

    waves = _compute_waves(plan)

    # Build table rows to compute column widths.
    header = ("Wave", "Status", "Step", "Agent", "Depends On")
    rows: list[tuple[str, str, str, str, str]] = []
    for wave_idx, wave in enumerate(waves):
        for step in wave:
            status = _step_status(step, completed, step_outcomes)
            symbol = status_symbols[status]
            deps = ", ".join(step.depends_on) if step.depends_on else "-"
            rows.append((
                str(wave_idx),
                symbol,
                step.id,
                step.agent_type or step.type,
                deps,
            ))

    # Compute column widths.
    col_widths = [len(h) for h in header]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    def _fmt_row(cells: tuple[str, ...]) -> str:
        parts = [cell.ljust(col_widths[i]) for i, cell in enumerate(cells)]
        return "  ".join(parts)

    lines: list[str] = []
    lines.append(_fmt_row(header))
    lines.append("  ".join("-" * w for w in col_widths))
    for row in rows:
        lines.append(_fmt_row(row))

    return "\n".join(lines)
