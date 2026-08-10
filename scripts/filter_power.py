"""Filter an OSM PBF down to power infrastructure using PyOsmium.

Equivalent to ``osmium tags-filter <input> nwr/power`` but implemented with the
``osmium`` Python package already declared in pyproject.toml, so no external
osmium-tool binary is required.

Two passes are needed. The first collects the IDs of every node referenced by a
power-tagged way; the second writes the power objects plus those nodes. Without
the second pass, ways would be written with unresolvable coordinates and
PowerHandler would silently produce empty geometries.

Usage:
    python scripts/filter_power.py <input.osm.pbf> <output.osm.pbf>
"""

import sys
from pathlib import Path

import osmium


def filter_power(src: str, dst: str) -> None:
    """Writes power-tagged objects from ``src`` to ``dst`` with geometry nodes."""
    referenced: set[int] = set()
    for obj in osmium.FileProcessor(src).with_filter(osmium.filter.KeyFilter("power")):
        if obj.is_way():
            referenced.update(node.ref for node in obj.nodes)

    print(f"    {len(referenced):,} referenced geometry nodes")

    with osmium.SimpleWriter(dst, overwrite=True) as writer:
        for obj in osmium.FileProcessor(src):
            if "power" in obj.tags or (obj.is_node() and obj.id in referenced):
                writer.add(obj)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2

    src, dst = sys.argv[1], sys.argv[2]
    if not Path(src).is_file():
        print(f"error: input not found: {src}", file=sys.stderr)
        return 1

    filter_power(src, dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
