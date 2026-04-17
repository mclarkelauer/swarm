"""CLI command: swarm update — pull latest from GitHub and reinstall."""

from __future__ import annotations

import subprocess
from pathlib import Path

import click


def _get_repo_root() -> Path:
    """Return the root of the swarm git repository."""
    # Walk up from this file to find the repo root (contains pyproject.toml + .git)
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() and (parent / ".git").exists():
            return parent
    raise click.ClickException(
        "Cannot locate swarm repository root. "
        "Is swarm installed from a git checkout?"
    )


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a shell command, optionally capturing output."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        text=True,
        capture_output=capture,
    )


def _get_head(repo_root: Path) -> str:
    """Return the current HEAD commit hash."""
    result = _run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture=True,
    )
    return result.stdout.strip()


def _show_changelog(repo_root: Path, old_head: str, new_head: str) -> None:
    """Print a summary of commits between old_head and new_head."""
    if old_head == new_head:
        click.echo()
        click.secho("Already up to date.", fg="yellow")
        return

    result = _run(
        ["git", "log", "--oneline", "--no-decorate", f"{old_head}..{new_head}"],
        cwd=repo_root,
        capture=True,
    )
    commits = result.stdout.strip()
    if not commits:
        return

    lines = commits.splitlines()
    click.echo()
    click.secho(f"Changes ({len(lines)} commit{'s' if len(lines) != 1 else ''}):", bold=True)
    for line in lines:
        click.echo(f"  {line}")


@click.command()
@click.option(
    "--branch",
    default=None,
    help="Branch to pull (default: current branch).",
)
@click.option(
    "--dev",
    is_flag=True,
    default=False,
    help="Also install dev dependencies (pytest, ruff, mypy).",
)
@click.option(
    "--pull-only",
    is_flag=True,
    default=False,
    help="Only pull, don't reinstall.",
)
@click.option(
    "--install-only",
    is_flag=True,
    default=False,
    help="Only reinstall, don't pull.",
)
def update(branch: str | None, dev: bool, pull_only: bool, install_only: bool) -> None:
    """Pull the latest code from GitHub and reinstall.

    Runs `git pull` in the swarm repository, then executes `install.sh`
    to rebuild and reinstall the swarm and swarm-mcp commands.
    """
    repo_root = _get_repo_root()
    install_script = repo_root / "install.sh"

    if not install_script.exists():
        raise click.ClickException(f"install.sh not found at {install_script}")

    # --- Pull ---
    if not install_only:
        click.echo()
        click.secho("Pulling latest from GitHub...", bold=True)
        click.echo()

        if branch:
            _run(["git", "checkout", branch], cwd=repo_root)

        old_head = _get_head(repo_root)

        result = _run(["git", "pull", "--ff-only"], cwd=repo_root, check=False)
        if result.returncode != 0:
            raise click.ClickException(
                "git pull failed. You may have local changes that conflict. "
                "Resolve them and retry, or use --install-only to skip the pull."
            )

        new_head = _get_head(repo_root)
        _show_changelog(repo_root, old_head, new_head)

        click.echo()
        click.secho("Pull complete.", fg="green")

    if pull_only:
        click.echo("Skipping install (--pull-only).")
        return

    # --- Install ---
    click.echo()
    click.secho("Running install.sh...", bold=True)
    click.echo()

    install_cmd = [str(install_script)]
    if dev:
        install_cmd.append("--dev")

    result = _run(install_cmd, cwd=repo_root, check=False)
    if result.returncode != 0:
        raise click.ClickException("install.sh failed. See output above.")

    click.echo()
    click.secho("Swarm updated successfully!", fg="green", bold=True)
    click.echo()
