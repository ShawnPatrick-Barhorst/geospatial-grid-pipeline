# Grid Engine

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Package Manager](https://img.shields.io/badge/uv-supported-261230)](https://github.com/astral-sh/uv)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**Grid Engine** is a data pipeline designed to convert raw OSM data, into a circuit level graph network representation.

---
## Overview

OSM models transmission as geographic corridors, not electrically isolated circuits. Meaning that a way in OSM can be tagged ```{circuits=3, voltage=500000;161000}``` representing 3 individual circuits at 2 voltages on shared towers.

Graph OSM as-is, and you get only a geographic representation, of shared infrastructure, not a circuit representation of substation -> substation connections.

This framework uses a deterministic set of rules to, clean, impute, and extract the circuit-level representation from OSM data, in a reproduceable manner.

## Features

 - **OSM PBF → circuit-level graph** — transforms OSM `.pbf` extracts into NetworkX graphs.
- **Circuit-level de-aggregation** — breaks transmission corridors into their individual circuits.
- **Tap detection** — identifies mid-span T-taps and models them as explicit nodes in the graph.
- **Missing data imputation** — fills missing circuit counts by propagating from neighboring segments.
- **Multi-voltage separation** — splits shared-tower corridors so voltage levels stay electrically independent.
- **Toy network builder** — hand-written YAML scenarios for testing topology cases.


## Installation

```bash
git clone https://github.com/<user>/geospatial-grid-pipeline.git
cd geospatial-grid-pipeline
uv sync
```

## Getting data

Grid Engine reads OSM PBF extracts. The included script downloads a region from
[Geofabrik](https://download.geofabrik.de/) and filters it to power
infrastructure:

```bash
scripts/fetch_region.sh tennessee
```

This writes `data/tennessee_power.osm.pbf` (~6 MB for Tennessee) and takes a
couple of minutes. 

> **Note:** Grid Engine has so far only been run against Tennessee. OSM power
> tagging conventions vary by region.


## Quickstart

```python
from grid_engine.ingestion import PowerHandler, ways_to_geodataframe
from grid_engine import GridEngine

handler = PowerHandler()
handler.apply_file("data/tennessee_power.osm.pbf", locations=True)

line_gdf = ways_to_geodataframe([w for w in handler.ways if w['type'] == 'line'])
substation_gdf = ways_to_geodataframe([w for w in handler.ways if w['type'] == 'substation'])

GE = GridEngine(line_gdf, substation_gdf, m_buffer=100, voltage_selection=[161000])
GE.run()

GE.networkx_graph     # NetworkX MultiGraph: substations and taps as nodes, circuits as edges
GE.circuit_terminals  # one row per resolved circuit
```

`m_buffer` is the distance in meters within which a dead-end line endpoint will
snap to a nearby substation. `voltage_selection` restricts the run to specific
voltages (in volts); omit it to process all.

See [`notebooks/grid_engine_tennessee.ipynb`](notebooks/grid_engine_tennessee.ipynb)
for a worked example with real data.

## Future Plans

A list of plans as the repository becomes more mature and approaches an official release.

- **Voltage imputation** — fill missing transmission corridor voltages from neighboring corridors.
- **Cross-referencing circuit count imputation** — infer counts for circuits with shared geometry by cross-referencing corridor totals.
- **Unit tests** — drive the existing YAML topology fixtures through pytest.
- **Interactive graph visualization** — replace the placeholder visualizer with a mature interactive renderer.
- **Junction diagnostics** — flag junctions the splicer could not reconcile, instead of silently fusing them.
- **Run logging** — structured logging for visibility and defensibility.
- **Nationwide scale** — extend beyond single-region extracts to the full United States.
- **Spark implementation** — a distributed backend behind the existing gateway layer for large transmission networks.

## License

Distributed under the Apache 2.0 License. See `LICENSE` for more information.