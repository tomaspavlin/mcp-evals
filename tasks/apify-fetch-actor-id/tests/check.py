from pathlib import Path

from rewardkit import criterion

EXPECTED_ID = "moJRLRc85AitArpNN"


@criterion
def actor_id_matches(workspace: Path) -> bool:
    return (workspace / "actor_id.txt").read_text().strip() == EXPECTED_ID
