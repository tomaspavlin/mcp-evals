from pathlib import Path

import yaml

from mcp_evals.integrations.model import Integration

INTEGRATIONS_DIR = Path("integrations")


def load_integration(name: str, root: Path = INTEGRATIONS_DIR) -> Integration:
    """Load integrations/<name>/integration.yaml. instruction.md alongside is
    auto-discovered and attached if present."""
    integration_dir = root / name
    yaml_path = integration_dir / "integration.yaml"
    if not yaml_path.is_file():
        raise FileNotFoundError(
            f"Integration '{name}' not found: missing {yaml_path}"
        )

    data = yaml.safe_load(yaml_path.read_text())
    integration = Integration.model_validate(data)

    instruction_md = integration_dir / "instruction.md"
    if instruction_md.is_file():
        integration.instruction_path = instruction_md

    return integration
