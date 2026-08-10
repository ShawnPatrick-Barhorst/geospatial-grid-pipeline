#!/usr/bin/env bash
#
# Download a Geofabrik region extract and filter it down to power infrastructure.
#
# Produces two files in data/ at the repo root:
#   <region>-latest.osm.pbf   raw Geofabrik extract (large, ~175M for Tennessee)
#   <region>_power.osm.pbf    power-tagged subset (~6M for Tennessee)
#
# The filtered file is what grid_engine.ingestion.PowerHandler expects as input.
# Both are gitignored (*.pbf); regenerate with this script rather than committing.
#
# Requires only `uv sync` -- filtering runs through PyOsmium (scripts/filter_power.py),
# not the separate osmium-tool CLI binary.
#
# Usage:
#   scripts/fetch_region.sh tennessee
#   scripts/fetch_region.sh tennessee --keep-raw
#   REGION_PATH=europe/germany/bayern scripts/fetch_region.sh bayern
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

REGION="${1:-tennessee}"
KEEP_RAW=0
[[ "${2:-}" == "--keep-raw" ]] && KEEP_RAW=1

# Geofabrik organizes extracts by continent/country/subregion. Override
# REGION_PATH for regions outside the US.
REGION_PATH="${REGION_PATH:-north-america/us/${REGION}}"
BASE_URL="https://download.geofabrik.de"
# Anchored to the repo root so output lands in the same place regardless of the
# directory the script is invoked from. data/ is gitignored.
OUT_DIR="${OUT_DIR:-${REPO_ROOT}/data}"

RAW="${OUT_DIR}/${REGION}-latest.osm.pbf"
FILTERED="${OUT_DIR}/${REGION}_power.osm.pbf"

command -v uv >/dev/null || {
    echo "error: uv not found. See https://docs.astral.sh/uv/ to install." >&2
    exit 1
}

mkdir -p "$OUT_DIR"

if [[ -f "$FILTERED" ]]; then
    echo "==> $FILTERED already exists; delete it to rebuild."
    exit 0
fi

if [[ -f "$RAW" ]]; then
    echo "==> Reusing existing $RAW"
else
    echo "==> Downloading ${REGION} from Geofabrik"
    # -C - resumes a partial download; extracts are large enough that a dropped
    # connection midway is worth recovering from.
    curl -fL -C - --progress-bar \
        "${BASE_URL}/${REGION_PATH}-latest.osm.pbf" -o "$RAW"
fi

echo "==> Filtering to power infrastructure (takes a couple of minutes)"
# Uses PyOsmium via scripts/filter_power.py rather than the osmium-tool CLI, so
# the only requirement is `uv sync`. Slower than the C++ tool but keeps every
# dependency declared in pyproject.toml.
uv run --project "$SCRIPT_DIR/.." python "$SCRIPT_DIR/filter_power.py" "$RAW" "$FILTERED"

if (( KEEP_RAW )); then
    echo "==> Keeping raw extract at $RAW"
else
    echo "==> Removing raw extract (pass --keep-raw to keep it)"
    rm -f "$RAW"
fi

echo "==> Done: $FILTERED ($(du -h "$FILTERED" | cut -f1))"
