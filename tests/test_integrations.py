"""Locks integration loading from a custom root and explicit `skills:`
resolution (relative to integration.yaml, glob expansion, validation)."""

import pytest
from typer.testing import CliRunner

from mcp_evals.cli.main import app
from mcp_evals.config import RunConfig
from mcp_evals.integrations.loader import load_integration


def _write_integration(root, name, yaml_body):
    integration_dir = root / name
    integration_dir.mkdir(parents=True)
    (integration_dir / "integration.yaml").write_text(yaml_body)
    return integration_dir


def _write_skill(parent, name):
    skill = parent / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"# {name}\n")
    return skill


class TestCustomRoot:
    def test_loads_from_absolute_root(self, tmp_path):
        integration_dir = _write_integration(
            tmp_path / "my-integrations", "foo", "name: foo\n"
        )
        (integration_dir / "instruction.md").write_text("hi\n")

        integ = load_integration("foo", root=tmp_path / "my-integrations")

        assert integ.name == "foo"
        assert integ.instruction_path == integration_dir / "instruction.md"

    def test_missing_integration_names_full_path(self, tmp_path):
        with pytest.raises(FileNotFoundError, match=str(tmp_path)):
            load_integration("nope", root=tmp_path)

    def test_auto_discovers_skills_subdir_under_custom_root(self, tmp_path):
        integration_dir = _write_integration(tmp_path, "foo", "name: foo\n")
        skill = _write_skill(integration_dir / "skills", "my-skill")

        integ = load_integration("foo", root=tmp_path)

        assert integ.skills == [skill]


class TestExplicitSkills:
    def test_relative_entry_resolves_against_integration_dir(self, tmp_path):
        skill = _write_skill(tmp_path / "app-skills", "alpha")
        _write_integration(
            tmp_path, "foo", 'name: foo\nskills: ["../app-skills/alpha"]\n'
        )

        integ = load_integration("foo", root=tmp_path)

        assert [p.resolve() for p in integ.skills] == [skill.resolve()]

    def test_glob_expands_sorted(self, tmp_path):
        beta = _write_skill(tmp_path / "app-skills", "beta")
        alpha = _write_skill(tmp_path / "app-skills", "alpha")
        _write_integration(
            tmp_path, "foo", 'name: foo\nskills: ["../app-skills/*"]\n'
        )

        integ = load_integration("foo", root=tmp_path)

        assert [p.resolve() for p in integ.skills] == [
            alpha.resolve(),
            beta.resolve(),
        ]

    def test_glob_matching_nothing_raises(self, tmp_path):
        _write_integration(
            tmp_path, "foo", 'name: foo\nskills: ["../missing/*"]\n'
        )
        with pytest.raises(FileNotFoundError, match="matched nothing"):
            load_integration("foo", root=tmp_path)

    def test_entry_without_skill_md_raises(self, tmp_path):
        (tmp_path / "app-skills" / "broken").mkdir(parents=True)
        _write_integration(
            tmp_path, "foo", 'name: foo\nskills: ["../app-skills/broken"]\n'
        )
        with pytest.raises(FileNotFoundError, match="SKILL.md"):
            load_integration("foo", root=tmp_path)

    def test_explicit_entry_dedupes_against_auto_discovery(self, tmp_path):
        integration_dir = _write_integration(
            tmp_path, "foo", 'name: foo\nskills: ["skills/my-skill"]\n'
        )
        skill = _write_skill(integration_dir / "skills", "my-skill")

        integ = load_integration("foo", root=tmp_path)

        assert [p.resolve() for p in integ.skills] == [skill.resolve()]


class TestRunConfigFields:
    def test_round_trips_integrations_dir_and_jobs_dir(self, tmp_path):
        run = RunConfig.model_validate(
            {"integrations_dir": str(tmp_path / "i"), "jobs_dir": str(tmp_path / "j")}
        )
        assert run.integrations_dir == tmp_path / "i"
        assert run.jobs_dir == tmp_path / "j"

    def test_defaults_to_none(self):
        run = RunConfig()
        assert run.integrations_dir is None
        assert run.jobs_dir is None


class TestCliFlagOverridesConfig:
    def test_integrations_dir_flag_wins_over_config(self, tmp_path, monkeypatch):
        """The flag's root must be the one actually searched: the config points
        at a root where the integration exists, the flag at an empty one, so the
        run fails with the flag's path in the error."""
        config_root = tmp_path / "from-config"
        _write_integration(config_root, "foo", "name: foo\n")
        flag_root = tmp_path / "from-flag"
        flag_root.mkdir()
        config = tmp_path / "run.yaml"
        config.write_text(
            f"integration: foo\nintegrations_dir: {config_root}\n"
            "agents: [{name: oracle}]\n"
            "tasks: [{path: unused}]\n"
        )
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(
            app,
            ["run", "-c", str(config), "--integrations-dir", str(flag_root), "-y"],
        )

        assert result.exit_code != 0
        assert isinstance(result.exception, FileNotFoundError)
        assert str(flag_root) in str(result.exception)
