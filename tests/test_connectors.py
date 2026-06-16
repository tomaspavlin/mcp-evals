"""Locks connector-cell loading from a custom root and explicit `skills:`
resolution (relative to cell.yaml, glob expansion, validation)."""

import pytest
from typer.testing import CliRunner

from mcp_evals.cli.main import app
from mcp_evals.config import RunConfig
from mcp_evals.connectors.loader import load_connector_cell


def _write_cell(root, connector, channel, yaml_body):
    cell_dir = root / connector / channel
    cell_dir.mkdir(parents=True)
    (cell_dir / "cell.yaml").write_text(yaml_body)
    return cell_dir


def _write_skill(parent, name):
    skill = parent / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"# {name}\n")
    return skill


class TestCustomRoot:
    def test_loads_from_absolute_root(self, tmp_path):
        cell_dir = _write_cell(tmp_path / "my-connectors", "foo", "mcp", "{}\n")
        (cell_dir / "instruction.md").write_text("hi\n")

        cell = load_connector_cell("foo", "mcp", root=tmp_path / "my-connectors")

        assert cell.connector == "foo"
        assert cell.channel == "mcp"
        assert cell.instruction_path == cell_dir / "instruction.md"

    def test_missing_cell_names_full_path(self, tmp_path):
        with pytest.raises(FileNotFoundError, match=str(tmp_path)):
            load_connector_cell("nope", "mcp", root=tmp_path)

    def test_auto_discovers_skills_subdir_under_custom_root(self, tmp_path):
        cell_dir = _write_cell(tmp_path, "foo", "skill", "{}\n")
        skill = _write_skill(cell_dir / "skills", "my-skill")

        cell = load_connector_cell("foo", "skill", root=tmp_path)

        assert cell.skills == [skill]


class TestExplicitSkills:
    def test_relative_entry_resolves_against_cell_dir(self, tmp_path):
        skill = _write_skill(tmp_path / "app-skills", "alpha")
        _write_cell(tmp_path, "foo", "skill", 'skills: ["../../app-skills/alpha"]\n')

        cell = load_connector_cell("foo", "skill", root=tmp_path)

        assert [p.resolve() for p in cell.skills] == [skill.resolve()]

    def test_glob_expands_sorted(self, tmp_path):
        beta = _write_skill(tmp_path / "app-skills", "beta")
        alpha = _write_skill(tmp_path / "app-skills", "alpha")
        _write_cell(tmp_path, "foo", "skill", 'skills: ["../../app-skills/*"]\n')

        cell = load_connector_cell("foo", "skill", root=tmp_path)

        assert [p.resolve() for p in cell.skills] == [
            alpha.resolve(),
            beta.resolve(),
        ]

    def test_glob_matching_nothing_raises(self, tmp_path):
        _write_cell(tmp_path, "foo", "skill", 'skills: ["../missing/*"]\n')
        with pytest.raises(FileNotFoundError, match="matched nothing"):
            load_connector_cell("foo", "skill", root=tmp_path)

    def test_entry_without_skill_md_raises(self, tmp_path):
        (tmp_path / "app-skills" / "broken").mkdir(parents=True)
        _write_cell(tmp_path, "foo", "skill", 'skills: ["../../app-skills/broken"]\n')
        with pytest.raises(FileNotFoundError, match="SKILL.md"):
            load_connector_cell("foo", "skill", root=tmp_path)

    def test_explicit_entry_dedupes_against_auto_discovery(self, tmp_path):
        cell_dir = _write_cell(tmp_path, "foo", "skill", 'skills: ["skills/my-skill"]\n')
        skill = _write_skill(cell_dir / "skills", "my-skill")

        cell = load_connector_cell("foo", "skill", root=tmp_path)

        assert [p.resolve() for p in cell.skills] == [skill.resolve()]


class TestRunConfigFields:
    def test_round_trips_connectors_dir_and_jobs_dir(self, tmp_path):
        run = RunConfig.model_validate(
            {"connectors_dir": str(tmp_path / "c"), "jobs_dir": str(tmp_path / "j")}
        )
        assert run.connectors_dir == tmp_path / "c"
        assert run.jobs_dir == tmp_path / "j"

    def test_defaults_to_none(self):
        run = RunConfig()
        assert run.connectors_dir is None
        assert run.jobs_dir is None


class TestCliFlagOverridesConfig:
    def test_connectors_dir_flag_wins_over_config(self, tmp_path, monkeypatch):
        """The flag's root must be the one actually searched: the config points
        at a root where the cell exists, the flag at an empty one, so the
        run fails with the flag's path in the error."""
        config_root = tmp_path / "from-config"
        _write_cell(config_root, "foo", "mcp", "{}\n")
        flag_root = tmp_path / "from-flag"
        flag_root.mkdir()
        config = tmp_path / "run.yaml"
        config.write_text(
            f"channel: mcp\nconnectors: [foo]\nconnectors_dir: {config_root}\n"
            "agents: [{name: oracle}]\n"
            "tasks: [{path: unused}]\n"
        )
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(
            app,
            ["run", "-c", str(config), "--connectors-dir", str(flag_root), "-y"],
        )

        assert result.exit_code != 0
        assert isinstance(result.exception, FileNotFoundError)
        assert str(flag_root) in str(result.exception)
