#!/usr/bin/env bash
# Совместимость прежнего MODEL=tinyllama|qwen; pinned ревизия/размер/SHA-256 — models.json.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/download_model.py" --model "${MODEL:-tinyllama}" "$@"
