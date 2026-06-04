from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point
from typing import Optional

import re
import math


_LINE_TYPES = {"line", "minor_line", "cable"}


def _split_way(way, end_nodes: set, line_types: set[str]) -> list[dict]:
    if way.type not in line_types:
        return []

    intermediate_nodes = way.node_refs[1:-1]
    matches = [node for node in intermediate_nodes if node in end_nodes]

    if not matches:
        return []

    segments = []
    start_index = 0

    for match in matches:
        match_index = way.node_refs.index(match, start_index + 1)
        node_refs_segment = way.node_refs[start_index:match_index + 1]
        coords_segment = way.coords[start_index:match_index + 1]

        if len(node_refs_segment) < 2:
            start_index = match_index
            continue

        segments.append({
            "id": f"{way.id}_{start_index}_{match_index}",
            "osm_type": way.osm_type,
            "type": way.type,
            "voltage": way.voltage,
            "voltages": way.voltages,
            "tags": way.tags,
            "name": way.name,
            "start_node": node_refs_segment[0],
            "end_node": node_refs_segment[-1],
            "geometry": LineString(coords_segment),
            "node_refs": node_refs_segment,
            "coords": coords_segment,
            "max_voltage": way.max_voltage,
        })
        start_index = match_index

    if start_index < len(way.node_refs) - 1:
        node_refs_segment = way.node_refs[start_index:]
        coords_segment = way.coords[start_index:]

        segments.append({
            "id": f"{way.id}_{start_index}_end",
            "osm_type": way.osm_type,
            "type": way.type,
            "voltage": way.voltage,
            "voltages": way.voltages,
            "tags": way.tags,
            "name": way.name,
            "start_node": node_refs_segment[0],
            "end_node": node_refs_segment[-1],
            "geometry": LineString(coords_segment),
            "node_refs": node_refs_segment,
            "coords": coords_segment,
            "max_voltage": way.max_voltage,
        })

    return segments


def segment_ways_at_nodes(
    lines_gdf: gpd.GeoDataFrame, 
    line_types: Optional[set[str]] = None
) -> gpd.GeoDataFrame:
    
    """Splits powerlines into segments at nodes that are shared with other lines. This is important for accurately modeling the grid and identifying grid connectivity.

    Returns:
        GeoDataFrame: A new GeoDataFrame with powerlines split into segments at shared nodes.
    """
    
    if line_types is None:
        line_types = _LINE_TYPES
    
    end_nodes = set(lines_gdf['node_refs'].apply(lambda x: x[0])) | set(lines_gdf['node_refs'].apply(lambda x: x[-1]))
    
    new_ways = []
    for way in lines_gdf.itertuples():
        new_ways.extend(_split_way(way, end_nodes, line_types))

    if not new_ways:
        return lines_gdf

    needs_split = lines_gdf.apply(
        lambda way: way["type"] in line_types
        and way["start_node"] != way["end_node"]
        and any(node in end_nodes for node in way["node_refs"][1:-1]),
        axis=1,
    )

    new_gdf = gpd.GeoDataFrame(
        new_ways,
        geometry=[w["geometry"] for w in new_ways],
        crs="EPSG:4326",
    )
    return pd.concat([lines_gdf[~needs_split], new_gdf], ignore_index=True)


def clean_voltages(v):
    """Cleans and standardizes voltage values from the OSM data. OSM voltage tags can be inconsistent, containing multiple values, units, or non-numeric characters. This function extracts numeric voltage values, converts them to a consistent unit (volts), and returns a list of voltages for each powerline.

    Args:
        v (_type_): The raw voltage value from the OSM data, which can be a string with multiple values and units, a single numeric value, or None.

    Returns:
        _type_: A list of cleaned voltage values in volts, or None if the input is invalid or missing. For example, an input of "10kV; 20kV" would return [10000, 20000], while an input of "15kV" would return [15000]. An input of None or an empty string would return None.
    """


    voltages = []

    # Strings may contain multiple voltage values separated by various delimiters
    if isinstance(v, str):
        split_voltages = re.split(r'[\s;:,]+', v)
        for part in split_voltages:
            if 'kva' in part.lower():
                match = re.search(r'[\d.]+', part)
                if match:
                    voltages.append(int(float(match.group()) * 1000))
            elif part.isdigit():
                voltages.append(int(part)) 
        return voltages
        
    # If it's a single numeric value, return it as a list for consistency
    elif isinstance(v, (int, float)):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        voltages.append(int(v))

    else:
        return None

def extract_line_substation_connections(line_gdf: gpd.GeoDataFrame, substation_gdf: gpd.GeoDataFrame, m_buffer: int) -> pd.DataFrame:
    
    starts = gpd.GeoDataFrame({
        'line_id': line_gdf['id'],
        'node_ref': line_gdf['node_refs'].apply(lambda refs: refs[0] if isinstance(refs, list) and len(refs) > 0 else None),
        'geometry': line_gdf['geometry'].apply(lambda g: Point(g.coords[0]) if isinstance(g, LineString) and len(g.coords) > 0 else None)
    }, crs=line_gdf.crs)

    ends = gpd.GeoDataFrame({
        'line_id': line_gdf['id'],
        'node_ref': line_gdf['node_refs'].apply(lambda refs: refs[-1] if isinstance(refs, list) and len(refs) > 0 else None),
        'geometry': line_gdf['geometry'].apply(lambda g: Point(g.coords[-1]) if isinstance(g, LineString) and len(g.coords) > 0 else None)
    }, crs=line_gdf.crs)

    endpoints = pd.concat([starts, ends], ignore_index=True)

    joined = gpd.sjoin(
        endpoints.to_crs(epsg=3857),
        substation_gdf[['id', 'geometry']].to_crs(epsg=3857),
        how='left',
        predicate='intersects'
    )

    matched = joined[joined['id'].notna()]
    unmatched = joined[joined['id'].isna()]

    # Buffer unmatched endpoints and try to match again
    if not unmatched.empty and m_buffer is not None:
        nearest = gpd.sjoin_nearest(
            unmatched.to_crs(epsg=3857),
            substation_gdf[['id', 'geometry']].to_crs(epsg=3857),
            how='left',
            distance_col='m_distance',
            rsuffix='nearest'
        )
        within_buffer = nearest[nearest['m_distance'] <= m_buffer]
        matched = pd.concat([matched, within_buffer], ignore_index=True)
        

    mapping = dict(zip(matched['node_ref'], matched['id'].astype(int)))
    return mapping

def voltage_splitting(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    # Ensure voltage is always a list
    gdf = gdf.copy()
    gdf['voltage'] = gdf['voltage'].apply(
        lambda v: v if isinstance(v, list) and len(v) > 0 else ([v] if v else [])
    )
    
    # Flag shared corridors before exploding
    gdf['shared_tower'] = gdf['voltage'].apply(lambda v: len(v) > 1)
    gdf['shared_tower_voltages'] = gdf['voltage']
    gdf['original_id'] = gdf['id']
    
    # Explode — one row per voltage
    gdf = gdf.explode('voltage', ignore_index=True)
    
    # Reconstruct unique ID per voltage
    gdf['id'] = gdf['original_id'].astype(str) + '_' + gdf['voltage'].astype(str)

    # Reconstruct node_refs list to reflect voltage-specific IDs for shared corridors
    gdf['node_refs'] = gdf.apply(
        lambda row: [int(f"{x}{row['voltage']}") for x in row['node_refs']],
        axis=1
    )
    
    return gdf