from pathlib import Path

EXPECTED_ID = "moJRLRc85AitArpNN"
OUTPUT = Path("/app/actor_id.txt")


def test_output_file_exists():
    assert OUTPUT.exists(), f"{OUTPUT} not created"


def test_output_matches_expected_id():
    content = OUTPUT.read_text().strip()
    assert content == EXPECTED_ID, f"got {content!r}, expected {EXPECTED_ID!r}"
