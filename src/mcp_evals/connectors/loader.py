import glob as _glob
from pathlib import Path

import yaml

from mcp_evals.connectors.model import ConnectorCell

CONNECTORS_DIR = Path("connectors")


def _resolve_skills(entries: list[Path], cell_dir: Path) -> list[Path]:
    """Resolve explicit `skills:` yaml entries relative to the cell dir.
    Globs are supported; each match must be a directory containing SKILL.md.
    A glob that matches nothing is an error rather than a silent no-op.
    """
    resolved: list[Path] = []
    for entry in entries:
        entry = entry.expanduser()
        pattern = entry if entry.is_absolute() else cell_dir / entry
        matches = sorted(Path(p) for p in _glob.glob(str(pattern)))
        if not matches:
            raise FileNotFoundError(
                f"Connector cell skill path matched nothing: {pattern}"
            )
        for match in matches:
            if not (match / "SKILL.md").is_file():
                raise FileNotFoundError(
                    f"Connector cell skill is not a skill directory "
                    f"(missing SKILL.md): {match}"
                )
            if match.resolve() not in {p.resolve() for p in resolved}:
                resolved.append(match)
    return resolved


def load_connector_cell(
    connector: str, channel: str, root: Path = CONNECTORS_DIR
) -> ConnectorCell:
    """Load <root>/<connector>/<channel>/cell.yaml. instruction.md, setup.sh,
    teardown.sh, and skills/<name>/SKILL.md alongside are auto-discovered."""
    cell_dir = root.expanduser() / connector / channel
    yaml_path = cell_dir / "cell.yaml"
    if not yaml_path.is_file():
        raise FileNotFoundError(
            f"Connector cell '{connector}/{channel}' not found: missing {yaml_path}"
        )

    data = yaml.safe_load(yaml_path.read_text()) or {}
    data["connector"] = connector
    data["channel"] = channel
    cell = ConnectorCell.model_validate(data)
    cell.skills = _resolve_skills(cell.skills, cell_dir)

    instruction_md = cell_dir / "instruction.md"
    if instruction_md.is_file():
        cell.instruction_path = instruction_md

    setup_sh = cell_dir / "setup.sh"
    if setup_sh.is_file():
        cell.setup_script_path = setup_sh

    teardown_sh = cell_dir / "teardown.sh"
    if teardown_sh.is_file():
        cell.teardown_script_path = teardown_sh

    skills_dir = cell_dir / "skills"
    if skills_dir.is_dir():
        explicit = {p.resolve() for p in cell.skills}
        for skill in sorted(skills_dir.iterdir()):
            if (
                skill.is_dir()
                and (skill / "SKILL.md").is_file()
                and skill.resolve() not in explicit
            ):
                cell.skills.append(skill)

    return cell
