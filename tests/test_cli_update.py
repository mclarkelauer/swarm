"""Tests for the ``swarm update`` command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from swarm.cli.main import cli


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def fake_repo(tmp_path: Path) -> Path:
    """Create a fake repo root with pyproject.toml, .git dir, and install.sh."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "swarm"\n')
    (tmp_path / ".git").mkdir()
    script = tmp_path / "install.sh"
    script.write_text("#!/bin/bash\nexit 0\n")
    script.chmod(0o755)
    return tmp_path


def _mock_heads(old: str = "aaa1111", new: str = "bbb2222"):
    """Return a side_effect for _get_head that returns old then new."""
    calls: list[str] = []

    def _get_head(repo_root: Path) -> str:
        if len(calls) == 0:
            calls.append(old)
            return old
        calls.append(new)
        return new

    return _get_head


class TestUpdate:
    def test_pull_and_install(self, runner: CliRunner, fake_repo: Path) -> None:
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        with patch("swarm.cli.update_cmd._get_repo_root", return_value=fake_repo), \
             patch("swarm.cli.update_cmd._run", mock_run), \
             patch("swarm.cli.update_cmd._get_head", side_effect=_mock_heads()), \
             patch("swarm.cli.update_cmd._show_changelog"):
            result = runner.invoke(cli, ["update"])

        assert result.exit_code == 0
        assert "Pulling latest" in result.output
        assert "Running install.sh" in result.output
        assert "updated successfully" in result.output

        # Should have called git pull and install.sh
        calls = mock_run.call_args_list
        assert len(calls) == 2
        assert calls[0].args[0] == ["git", "pull", "--ff-only"]
        assert str(fake_repo / "install.sh") in calls[1].args[0][0]

    def test_pull_only(self, runner: CliRunner, fake_repo: Path) -> None:
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        with patch("swarm.cli.update_cmd._get_repo_root", return_value=fake_repo), \
             patch("swarm.cli.update_cmd._run", mock_run), \
             patch("swarm.cli.update_cmd._get_head", side_effect=_mock_heads()), \
             patch("swarm.cli.update_cmd._show_changelog"):
            result = runner.invoke(cli, ["update", "--pull-only"])

        assert result.exit_code == 0
        assert "Pulling latest" in result.output
        assert "Skipping install" in result.output

        calls = mock_run.call_args_list
        assert len(calls) == 1
        assert calls[0].args[0] == ["git", "pull", "--ff-only"]

    def test_install_only(self, runner: CliRunner, fake_repo: Path) -> None:
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        with patch("swarm.cli.update_cmd._get_repo_root", return_value=fake_repo), \
             patch("swarm.cli.update_cmd._run", mock_run):
            result = runner.invoke(cli, ["update", "--install-only"])

        assert result.exit_code == 0
        assert "Pulling latest" not in result.output
        assert "Running install.sh" in result.output

        calls = mock_run.call_args_list
        assert len(calls) == 1
        assert str(fake_repo / "install.sh") in calls[0].args[0][0]

    def test_branch_checkout(self, runner: CliRunner, fake_repo: Path) -> None:
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        with patch("swarm.cli.update_cmd._get_repo_root", return_value=fake_repo), \
             patch("swarm.cli.update_cmd._run", mock_run), \
             patch("swarm.cli.update_cmd._get_head", side_effect=_mock_heads()), \
             patch("swarm.cli.update_cmd._show_changelog"):
            result = runner.invoke(cli, ["update", "--branch", "develop"])

        assert result.exit_code == 0
        calls = mock_run.call_args_list
        assert calls[0].args[0] == ["git", "checkout", "develop"]
        assert calls[1].args[0] == ["git", "pull", "--ff-only"]

    def test_dev_flag_passed_to_install(self, runner: CliRunner, fake_repo: Path) -> None:
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        with patch("swarm.cli.update_cmd._get_repo_root", return_value=fake_repo), \
             patch("swarm.cli.update_cmd._run", mock_run), \
             patch("swarm.cli.update_cmd._get_head", side_effect=_mock_heads()), \
             patch("swarm.cli.update_cmd._show_changelog"):
            result = runner.invoke(cli, ["update", "--dev"])

        assert result.exit_code == 0
        install_call = mock_run.call_args_list[-1]
        assert "--dev" in install_call.args[0]

    def test_git_pull_failure(self, runner: CliRunner, fake_repo: Path) -> None:
        mock_run = MagicMock(return_value=MagicMock(returncode=1))
        with patch("swarm.cli.update_cmd._get_repo_root", return_value=fake_repo), \
             patch("swarm.cli.update_cmd._run", mock_run), \
             patch("swarm.cli.update_cmd._get_head", return_value="aaa1111"):
            result = runner.invoke(cli, ["update"])

        assert result.exit_code != 0
        assert "git pull failed" in result.output

    def test_install_failure(self, runner: CliRunner, fake_repo: Path) -> None:
        call_count = 0

        def run_side_effect(
            cmd: list[str], *, cwd: Path, check: bool = True, capture: bool = False,
        ) -> MagicMock:
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            if call_count == 1:
                mock.returncode = 0  # git pull succeeds
            else:
                mock.returncode = 1  # install.sh fails
            return mock

        with patch("swarm.cli.update_cmd._get_repo_root", return_value=fake_repo), \
             patch("swarm.cli.update_cmd._run", side_effect=run_side_effect), \
             patch("swarm.cli.update_cmd._get_head", side_effect=_mock_heads()), \
             patch("swarm.cli.update_cmd._show_changelog"):
            result = runner.invoke(cli, ["update"])

        assert result.exit_code != 0
        assert "install.sh failed" in result.output

    def test_missing_install_script(self, runner: CliRunner, fake_repo: Path) -> None:
        (fake_repo / "install.sh").unlink()
        with patch("swarm.cli.update_cmd._get_repo_root", return_value=fake_repo):
            result = runner.invoke(cli, ["update"])

        assert result.exit_code != 0
        assert "install.sh not found" in result.output

    def test_repo_root_not_found(self, runner: CliRunner) -> None:
        from click import ClickException

        from swarm.cli.update_cmd import _get_repo_root

        with patch("swarm.cli.update_cmd.Path") as mock_path_cls:
            mock_file = MagicMock()
            mock_file.resolve.return_value = mock_file
            mock_file.parents = []
            mock_path_cls.__file__ = mock_file
            mock_path_cls.return_value = mock_file

            with pytest.raises(ClickException, match="Cannot locate"):
                _get_repo_root()

    def test_shows_changelog_after_pull(self, runner: CliRunner, fake_repo: Path) -> None:
        mock_changelog = MagicMock()

        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        with patch("swarm.cli.update_cmd._get_repo_root", return_value=fake_repo), \
             patch("swarm.cli.update_cmd._run", mock_run), \
             patch("swarm.cli.update_cmd._get_head", side_effect=_mock_heads("aaa", "bbb")), \
             patch("swarm.cli.update_cmd._show_changelog", mock_changelog):
            result = runner.invoke(cli, ["update"])

        assert result.exit_code == 0
        mock_changelog.assert_called_once_with(fake_repo, "aaa", "bbb")

    def test_changelog_already_up_to_date(self, runner: CliRunner, fake_repo: Path) -> None:
        """When HEAD doesn't change, show 'Already up to date.'."""
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        with patch("swarm.cli.update_cmd._get_repo_root", return_value=fake_repo), \
             patch("swarm.cli.update_cmd._run", mock_run), \
             patch("swarm.cli.update_cmd._get_head", return_value="aaa1111"):
            result = runner.invoke(cli, ["update"])

        assert result.exit_code == 0
        assert "Already up to date" in result.output

    def test_changelog_shows_commits(self, runner: CliRunner, fake_repo: Path) -> None:
        """When there are new commits, list them."""
        log_result = MagicMock(stdout="bbb2222 Add feature X\nccc3333 Fix bug Y")

        def run_side_effect(
            cmd: list[str], *, cwd: Path, check: bool = True, capture: bool = False,
        ) -> MagicMock:
            if cmd[:2] == ["git", "log"]:
                return log_result
            return MagicMock(returncode=0)

        with patch("swarm.cli.update_cmd._get_repo_root", return_value=fake_repo), \
             patch("swarm.cli.update_cmd._run", side_effect=run_side_effect), \
             patch("swarm.cli.update_cmd._get_head", side_effect=_mock_heads("aaa", "bbb")):
            result = runner.invoke(cli, ["update"])

        assert result.exit_code == 0
        assert "Changes (2 commits):" in result.output
        assert "Add feature X" in result.output
        assert "Fix bug Y" in result.output

    def test_changelog_singular_commit(self, runner: CliRunner, fake_repo: Path) -> None:
        log_result = MagicMock(stdout="bbb2222 Add feature X")

        def run_side_effect(
            cmd: list[str], *, cwd: Path, check: bool = True, capture: bool = False,
        ) -> MagicMock:
            if cmd[:2] == ["git", "log"]:
                return log_result
            return MagicMock(returncode=0)

        with patch("swarm.cli.update_cmd._get_repo_root", return_value=fake_repo), \
             patch("swarm.cli.update_cmd._run", side_effect=run_side_effect), \
             patch("swarm.cli.update_cmd._get_head", side_effect=_mock_heads("aaa", "bbb")):
            result = runner.invoke(cli, ["update"])

        assert result.exit_code == 0
        assert "Changes (1 commit):" in result.output

    def test_help_text(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["update", "--help"])
        assert result.exit_code == 0
        assert "Pull the latest code from GitHub" in result.output
        assert "--branch" in result.output
        assert "--dev" in result.output
        assert "--pull-only" in result.output
        assert "--install-only" in result.output
