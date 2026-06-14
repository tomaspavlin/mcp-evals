#!/bin/bash
set -e

curl -LsSf https://astral.sh/uv/0.9.7/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

uvx --from harbor-rewardkit==0.1.4 rewardkit /tests
