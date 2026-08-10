from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point
from typing import Optional
from numbers import Integral
import numpy as np
from collections import defaultdict

import math
from scipy.optimize import linear_sum_assignment


_LINE_TYPES = {"line", "minor_line", "cable"}
_TAP_PREFIX = "tap_"

# Small scalar applied to assignment cost to break ties between identical lanes.
# Far below any dot product (bounded by 1), serves to nudge not alter outcomes
_LANE_TIE_BREAK = 1e-6


# Large scalar applied to assignment cost of unpairable lines 
# well above any real dot product (bounded by 1)
_UNPAIRABLE = 1e6




def _split_way(way, end_nodes: set, line_types: set[str]) -> list[dict]:
    """Cuts a single way into segments wherever it passes through another way's endpoint.

    Parameters
    ----------
    way : namedtuple
        One row from 'lines_gdf.itertuples()', requiring 'type', 'node_refs',
        'coords', and 'id'. Every other field present is carried through onto
        each segment untouched.
    end_nodes : set
        Node ids that terminate some way in the dataset. An intermediate node
        appearing here is a junction, so the way is cut there.
    line_types : set[str]
        OSM types eligible for splitting. Ways of any other type are returned
        unsplit.

    Returns
    -------
    list[dict]
        One dict per segment, each with its own 'id' suffixed '_{start}_{end}',
        plus sliced 'geometry', 'node_refs', and 'coords'. Empty when the way
        is not an eligible type or crosses no junction, meaning no split is
        needed and the caller should keep the original.
    """

    if way.type not in line_types:
        return []

    intermediate_nodes = way.node_refs[1:-1]
    matches = [node for node in intermediate_nodes if node in end_nodes]

    if not matches:
        return []

    base = way._asdict()
    del base["Index"]

    split_indices = []
    idx = 0
    for match in matches:
        idx = way.node_refs.index(match, idx + 1)
        split_indices.append(idx)
    split_indices.append(len(way.node_refs) - 1)

    segments = []
    start_index = 0
    for end_index in split_indices:
        node_refs_segment = way.node_refs[start_index:end_index + 1]
        coords_segment = way.coords[start_index:end_index + 1]

        if len(node_refs_segment) >= 2:
            segment = base.copy()
            segment.update({
                "id": f"{way.id}_{start_index}_{end_index}",
                "geometry": LineString(coords_segment),
                "node_refs": node_refs_segment,
                "coords": coords_segment,
            })
            segments.append(segment)

        start_index = end_index

    return segments



def segment_ways_at_nodes(
    lines_gdf: gpd.GeoDataFrame, 
    line_types: Optional[set[str]] = None
) -> gpd.GeoDataFrame:

    """Splits powerlines into segments at nodes that are shared with other lines. This is important for accurately modeling the grid and identifying grid connectivity.

    Parameters
    ----------
    lines_gdf : gpd.GeoDataFrame
        All ways from ingestion, requiring 'id', 'type', 'node_refs', 'coords',
        and 'geometry'.
    line_types : set[str], optional
        OSM types eligible for splitting, by default '_LINE_TYPES'
        ({'line', 'minor_line', 'cable'}).

    Returns
    -------
    gpd.GeoDataFrame
        The input with every split way replaced by its segments, in EPSG:4326.
        Returned unchanged when nothing needed splitting.
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
        and way["node_refs"][0] != way["node_refs"][-1]
        and any(node in end_nodes for node in way["node_refs"][1:-1]),
        axis=1,
    )

    new_gdf = gpd.GeoDataFrame(
        new_ways,
        geometry=[w["geometry"] for w in new_ways],
        crs="EPSG:4326",
    )
    return pd.concat([lines_gdf[~needs_split], new_gdf], ignore_index=True)



def extract_line_substation_connections(line_gdf: gpd.GeoDataFrame, substation_gdf: gpd.GeoDataFrame, m_buffer: int) -> dict[str, str]:

    """Uses spatial joins to create a line endpoints->substation adjacency list. Handles instances where lines don't end directly in substations with m_buffer.

    Parameters
    ----------
    line_gdf : gpd.GeoDataFrame
        GeoDataFrame containing all ways representing transmission corridors/lines,
        requiring 'id', 'node_refs', 'geometry', and a set '.crs'.
    substation_gdf : gpd.GeoDataFrame
        GeoDataFrame containing substations, requiring 'id' and 'geometry'.
    m_buffer : int
        Search distance in meters for endpoints that miss a substation outright.
        Only dead ends are retried, so a line passing near a substation is not
        pulled into it.

    Returns
    -------
    dict[str, str]
        A dictionary representing adjacencies between line endpoints and substations
    """

    #TODO: Verify output dictionary is not silently dropping connections. Something I realized when using dicts for downstream adjacency dictionaries.
    
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

    node_counts = endpoints['node_ref'].value_counts().to_dict()

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
        # Drop the stale (all-NaN) join columns so the nearest-join's 'id'
        # doesn't collide and get suffixed away from matched['id'].
        unmatched_dead_ends = unmatched[unmatched['node_ref'].map(lambda ref: node_counts.get(ref, 0) == 1)].copy()

        if not unmatched_dead_ends.empty:
            unmatched_dead_ends = unmatched_dead_ends.drop(columns=['id', 'index_right'], errors='ignore')
            nearest_dead_ends = gpd.sjoin_nearest(
                unmatched_dead_ends.to_crs(epsg=3857),
                substation_gdf[['id', 'geometry']].to_crs(epsg=3857),
                how='left',
                distance_col='m_distance',
                rsuffix='nearest'
            )
            within_buffer_dead_ends = nearest_dead_ends[nearest_dead_ends['m_distance'] <= m_buffer]
            matched = pd.concat([matched, within_buffer_dead_ends], ignore_index=True)
    mapping = dict(zip(matched['node_ref'], matched['id'].astype(int)))
    return mapping



def _normalize_voltage_list(v) -> list:
    """Helper function to detect and coerce NaN or None values into a clean list of voltages.

    Parameters
    ----------
    v : list, float, int, or None
        A single voltage reading or a list of voltage values. Single NaN or 
        None inputs are converted to ``[None]``, while lists have their NaN 
        elements filtered out.

    Returns
    -------
    list
        A list of valid voltage values, or ``[None]`` if no valid values exist.
    """
    if isinstance(v, list):
        cleaned = [x for x in v if pd.notna(x)]
        return cleaned if cleaned else [None]

    if v is None:
        return [None]

    if isinstance(v, float) and math.isnan(v):
        return [None]

    return [v]



def _normalize_scalar_count(count) -> Optional[int]:
    """Coerces a scalar value into a valid integer count.

    Parameters
    ----------
    count : float, bool, int, str, or None
        The input scalar value to normalize into an integer count.

    Returns
    -------
    int or None
        The normalized integer value if `count` represents a valid whole
        number; otherwise ``None``.
    """


    if count is None:
        return None

    if pd.isna(count):
        return None

    if isinstance(count, bool):
        return None

    if isinstance(count, Integral):
        return int(count)

    if isinstance(count, float):
        if math.isnan(count):
            return None
        return int(count) if float(count).is_integer() else None

    if isinstance(count, str):
        raw = count.strip()
        if not raw:
            return None
        try:
            parsed = float(raw)
        except ValueError:
            return None
        if math.isnan(parsed):
            return None
        return int(parsed) if parsed.is_integer() else None

    return None



def _compute_circuit_counts(voltages, count) -> list:

    """Solve initial circuit counts per voltage using a rule based approach. 
        Circuits counts marked as ''None'' can be solved later using grid_engine.cleaning.propagate_circuit_counts.

    Parameters
    ----------
    voltages : int or list
        Either a list of unique voltages per line, or an int for single voltage lines.

    count : int
        Number of individual circuits per corridor.

    Returns
    -------
    list
        One count per voltage, aligned to 'voltages'. Entries are None where the
        rules cannot decide, leaving them for
        grid_engine.cleaning.propagate_circuit_counts to resolve.
    """

    voltages = voltages if isinstance(voltages, list) else [voltages]
    v_count = len(voltages)

    if isinstance(count, list):
        normalized = [_normalize_scalar_count(c) for c in count]
        if len(normalized) == v_count:
            return normalized

        non_null = [c for c in normalized if c is not None]
        count = non_null[0] if len(non_null) == 1 else None
    else:
        count = _normalize_scalar_count(count)

    if v_count == 0:
        return []

    # State 1: If circuit count is equal to unique voltage count, split circuit count into a list of 1s
    if v_count == count and count is not None:
        return [1] * v_count

    # State 2: If there is 1 voltage but multiple circuits, assign the circuit count to that voltage
    if v_count == 1 and count is not None and count > 1:
        return [count] * v_count

    # State 3: If there are multiple voltages but only 1 circuit, flag
    if v_count > 1 and (count == 1 or count is None):
        return [None] * v_count
    
    return [None] * v_count



def voltage_splitting(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:

    """Explodes transmission corridors into duplicate lines representing circuits of unique voltage. Appends the unique voltage to each id for seperability and identification.

    Parameters
    ----------
    gdf : gpd.GeoDataFrame
        Transmission corridors, requiring 'id', 'voltage', 'node_refs', and
        'geometry'. 'counts' is optional and created empty when absent, leaving
        every circuit count for propagate_circuit_counts to resolve.

    Returns
    -------
    GeoDataFrame
        GeoDataFrame representing all transmission corridors, lines, and circuits collected from OSM data.
    """

    # Ensure voltage is always a list
    gdf = gdf.copy()
    crs = gdf.crs
    gdf['voltage'] = gdf['voltage'].apply(_normalize_voltage_list)

    if 'counts' not in gdf.columns:
        gdf['counts'] = None

    gdf['counts'] = [_compute_circuit_counts(v, c) for v, c in zip(gdf['voltage'], gdf['counts'])]

    # Flag shared corridors before exploding
    gdf['shared_tower'] = gdf['voltage'].apply(lambda v: len(v) > 1)
    gdf['shared_tower_voltages'] = gdf['voltage']
    gdf['original_id'] = gdf['id']
    
    #TODO: Consider cleaning this, going from dataframe to geodataframe is scuffed
    # Explode — one row per voltage
    # Use pandas explode for multiple columns; GeoPandas explode only supports
    # a single geometry column and will error when passed a list.
    gdf = pd.DataFrame(gdf).explode(['voltage', 'counts'], ignore_index=True)
    gdf = gpd.GeoDataFrame(gdf, geometry='geometry', crs=crs)
    
    # Reconstruct unique ID per voltage
    gdf['id'] = gdf['original_id'].astype(str) + '_' + gdf['voltage'].astype(str)

    # Reconstruct node_refs list to reflect voltage-specific IDs for shared corridors
    gdf['node_refs'] = gdf.apply(
        lambda row: [
            int(f"{x}{row['voltage']}") if pd.notna(row['voltage']) else int(x)
            for x in row['node_refs']
        ],

        axis=1
    )
    
    return gdf



def simplify_graph(gdf: gpd.GeoDataFrame, line_types: list[str]) -> gpd.GeoDataFrame:
    """Not currently used. Simplifies specified line types with multiple chaining node_refs, into simplified versions containing only the first and last node, used for substation and line to line connectivity.

    Parameters
    ----------
    gdf : gpd.GeoDataFrame
        GeoDataFrame containing all transmission corridors.
    line_types : list[str]
        List of line types, used to mask this function to a certain subset of line types.

    Returns
    -------
    gpd.GeoDataFrame
        GeoDataFrame containing all transmission corridors where specified line types have intermediary node_refs removed.
    """

    # Only simplify lines that are not of the specified types (e.g., 'line', 'minor_line', 'cable')
    to_simplify = gdf[~gdf['type'].isin(line_types)]

    # Simplify node_refs and geometry for the selected lines by keeping only the start and end nodes
    to_simplify['node_refs'] = to_simplify.apply(
        lambda row: [row['node_refs'][0], row['node_refs'][-1]] if isinstance(row['node_refs'], list) and len(row['node_refs']) > 1 else row['node_refs'],
        axis=1
    )  

    # Simplify geometry to a single point if it's a LineString with more than 2 coordinates, otherwise keep it as is 
    to_simplify['geometry'] = to_simplify.apply(
        lambda row: Point(row['geometry'].coords[0]) if isinstance(row['geometry'], LineString) and len(row['geometry'].coords) > 0 else row['geometry'],
        axis=1
    )   

    # Combine the simplified lines back with the rest of the GeoDataFrame
    simplified_gdf = pd.concat([to_simplify, gdf[gdf['type'].isin(line_types)]], ignore_index=True)

    return simplified_gdf



def get_line_vector(line_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """Computes the local heading of each line at both of its endpoints.

    Creates two records per row, one per endpoint, each tangential to its adjacent vertex and pointing away from its node into the line.

    Nodes that aren't a segment endpoint receive no record.

    Parameters
    ----------
    line_gdf : gpd.GeoDataFrame
        Transmission corridors, requiring 'id', 'node_refs', and LineString
        'geometry'.

    Returns
    -------
    pd.DataFrame
        One row per line endpoint with 'id', 'node', and 'vector', where
        'vector' is a unit numpy array of shape (2,).
    """

    records = []
    
    for idx, row in line_gdf.iterrows():
        coords = np.array(row.geometry.coords)
        if len(coords) < 2:
            continue

        line_id = row['id']
        start_node = row['node_refs'][0]
        end_node = row['node_refs'][-1]

        v_start = coords[1] - coords[0]
        norm_start = np.linalg.norm(v_start)
        if norm_start > 0:
            records.append(
                {
                    'id': line_id,
                    'node': start_node,
                    'vector': v_start / norm_start
                }
            )

        v_end = coords[-2] - coords[-1]
        norm_end = np.linalg.norm(v_end)
        if norm_end > 0:
            records.append(
                {
                    'id': line_id,
                    'node': end_node,
                    'vector': v_end / norm_end
                }
            )

    return pd.DataFrame(records)



def _split_by_line_id(line_ids):
    """Splits a junction into incoming and outgoing using line id's. Used downstream for linear sum assignment.
        Incoming and outgoing is language adopted from linear sum assignment itself, this does not imply directionality in any way.

    Parameters
    ----------
    line_ids : str
        The base ID assigned to each transmission corridor before being broken down into individual lines.

    Returns
    -------
    set(list[incoming], list[outgoing]) or None
        Returns particular lines divided by each group, or returns None if incoming/outgoing cannot be cleanly resolved with this rule set.
    """
    if line_ids is None:
        return None

    groups = defaultdict(list)
    for index, line_id in enumerate(line_ids):
        groups[line_id].append(index)

    if len(groups) < 2:
        return None

    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), str(kv[0])))

    if len(groups) == 2:
        (_, side_a), (_, side_b) = ordered
        return side_a, side_b

    # Three or more lines: still decidable when one line brings exactly half the strands
    half, remainder = divmod(len(line_ids), 2)
    if remainder == 0:
        biggest_id, biggest = ordered[0]
        if len(biggest) == half:
            rest = [i for i in range(len(line_ids)) if line_ids[i] != biggest_id]
            return biggest, rest

    return None



def _split_incoming_outgoing(norm_vectors, line_ids=None):
    """In the event '_split_by_line_id()' cannnot resolve incoming/outgoing, this function serves as a fallback which attempts to resolve the conflict using geometry.

    Parameters
    ----------
    norm_vectors : np.ndarray
        Unit bearings of every strand at this node, shape (degree, 2), each
        pointing away from the node into its strand.
    line_ids : list[str], optional
        Base corridor id per strand, positionally aligned to 'norm_vectors',
        by default None. Passed straight to '_split_by_line_id()'.

    Returns
    -------
    tuple[list[int], list[int]]
        Indices into 'norm_vectors' split into the two sides, named left and
        right after the geometry rather than any direction of flow.
    """
    by_id = _split_by_line_id(line_ids)
    if by_id is not None:
        return by_id

    mean_dir = norm_vectors.mean(axis=0)

    if np.linalg.norm(mean_dir) < 1e-9:
        # Bearings cancel: already a balanced corridor, any strand serves
        axis = norm_vectors[0]
    else:
        axis = norm_vectors[int(np.argmin(norm_vectors @ mean_dir))]

    projections = norm_vectors @ axis
    left = [i for i in range(len(norm_vectors)) if projections[i] >= 0]
    right = [i for i in range(len(norm_vectors)) if projections[i] < 0]

    return left, right



def _handedness(axis, vector) -> float:
    """Signed cross product: Used to determine which side of 'axis' does 'vector' lie on.

    Used for taps with the assumption that transmission lines rarely cross one another. If a tap occurs on the left, it is assigned to the line representing the left, vice verasa.

    Parameters
    ----------
    axis : np.ndarray
        Reference bearing of shape (2,), facing along the corridor.
    vector : np.ndarray
        Bearing of shape (2,) to place relative to 'axis'.

    Returns
    -------
    float
        Positive when 'vector' lies to the left of 'axis', negative to the
        right, and zero when the two are collinear.
    """
    return float(axis[0] * vector[1] - axis[1] * vector[0])





def _match_strands_at_node(
    strand_ids, norm_vectors, strand_seqs=None, line_ids=None
):
    """Utilizes linear sum assignment to optimally assign line pairs at each node. 
        In the event there is an odd number of lines at a node or linear sum assignment is unable to assign a line pair, 
        this function returns a list of unmatched strands to be treated as circuit taps downstream.

    Parameters
    ----------
    strand_ids : list[str]
        Every strand meeting at this node, one entry per contact.
    norm_vectors : np.ndarray
        Unit bearings of every strand at this node, shape (degree, 2), each
        pointing away from the node into its strand.
    strand_seqs : list[int], optional
        Lane number within each strand's corridor, positionally aligned to
        'strand_ids', by default None. Used only to break ties between
        otherwise identical pairings, so lanes stay on their own side across a
        segment boundary; without it those ties resolve arbitrarily.
    line_ids : list[str], optional
        Base corridor id per strand, positionally aligned to 'strand_ids', by
        default None. Bars two strands of the same line from pairing with each
        other, and lets '_split_by_line_id()' settle the node by identity
        before geometry is consulted.

    Returns
    -------
    tuple[list[tuple[str, str]], list[str]]
        Sorted strand pairs continuing through the node, and the strand ids
        left over, which are branches to be treated as taps downstream.
    """
    left, right = _split_incoming_outgoing(norm_vectors, line_ids)

    pairs = []
    matched = set()

    if left and right:
        # Cost is the dot product, so straight-through (~ -1.0) is cheapest
        cost = np.empty((len(left), len(right)))
        for a, i in enumerate(left):
            for b, j in enumerate(right):
                cost[a, b] = float(np.dot(norm_vectors[i], norm_vectors[j]))

                # Last Resort: Cleans up junctions that could not settle by
                if line_ids is not None and line_ids[i] == line_ids[j]:
                    cost[a, b] = _UNPAIRABLE

                # Keep a lane on its own side across a segment boundary
                elif strand_seqs is not None and strand_seqs[i] == strand_seqs[j]:
                    cost[a, b] -= _LANE_TIE_BREAK

        rows, cols = linear_sum_assignment(cost)

        # If N pairs arrive and N pairs leave, all lines are paired (angle agnostic)
        for a, b in zip(rows, cols):
            if cost[a, b] >= _UNPAIRABLE:
                continue  # barred pairing the solver took only to fill the matrix
            i, j = left[a], right[b]
            pairs.append(tuple(sorted((strand_ids[i], strand_ids[j]))))
            matched.update((strand_ids[i], strand_ids[j]))

    pairs.sort()
    unmatched = [s for s in strand_ids if s not in matched]

    return pairs, unmatched


def _assign_branch_to_lane(
    branch_index, pairs, strand_ids, norm_vectors, strand_seqs=None
):
    """Chooses which through-lane at a node, an unmatched line taps onto.

        In the event that there are parallel through-lines and 'build_string_adjacency_list()', identifies a tap, 
        a decision had to be made as to which through-line that tap belongs to. Under the base assumption that 
        transmission lines do not cross, we use signed_handedness to determine whether the tap is on the left or right
        of the transmission corridor and assigns the tap accordingly.

    Parameters
    ----------
    branch_index : int
        Position of the tapping strand within 'strand_ids' and 'norm_vectors'.
    pairs : list[tuple[str, str]]
        Through-lanes at this node, as returned by '_match_strands_at_node()'.
    strand_ids : list[str]
        Every strand meeting at this node, one entry per contact.
    norm_vectors : np.ndarray
        Unit bearings of every strand at this node, shape (degree, 2), each
        pointing away from the node into its strand.
    strand_seqs : list[int], optional
        Lane number within each strand's corridor, positionally aligned to
        'strand_ids', by default None. Orders the lanes when handedness cannot
        separate them; without it that ordering falls back to strand id.

    Returns
    -------
    tuple[str, str] or None
        The lane the branch taps into, or None when there are no lanes to tap.
    """
    if not pairs:
        return None
    if len(pairs) == 1:
        return pairs[0]

    position = {strand_id: i for i, strand_id in enumerate(strand_ids)}

    # Axis: the straightest pair, tail-to-head from its smaller strand id.
    def straightness(pair):
        a, b = position[pair[0]], position[pair[1]]
        return float(np.dot(norm_vectors[a], norm_vectors[b]))

    axis_pair = min(pairs, key=lambda p: (straightness(p), p))
    tail = position[axis_pair[0]]
    axis = -norm_vectors[tail]  # bearings point outward; flip to face along it

    branch_side = _handedness(axis, norm_vectors[branch_index])

    def lane_side(pair):
        a, b = position[pair[0]], position[pair[1]]
        return (_handedness(axis, norm_vectors[a])
                + _handedness(axis, norm_vectors[b])) / 2.0

    spread = [lane_side(p) for p in pairs]
    if max(spread) - min(spread) > 1e-9:
        # Lanes are geometrically distinct: take the one nearest the branch.
        return min(pairs, key=lambda p: (abs(lane_side(p) - branch_side), p))

    # Order lanes by strand_seq and let the branches signed_cross determine a side
    def lane_seq(pair):
        if strand_seqs is None:
            return pair
        return (min(strand_seqs[position[s]] for s in pair), pair)

    ordered = sorted(pairs, key=lane_seq)
    return ordered[-1] if branch_side < 0 else ordered[0]


def build_string_adjacency_list(
    joints_df: gpd.GeoDataFrame,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:

    """Primary engine used to create line to line pairs at each node.

       This function finds the optimal solution to take single transmission lines created when exploding transmission lines by circuit count,
       and splices them together to create as accurate of a representation of the circuit level transmission network as possible.

       This algorithm ignores dead-ends (nodes with degree 1) and uses a simple assignment for through nodes (nodes with degree 2)

       For nodes degree >= 3, Linear sum assignment for optimal assignment as opposed to greedy methods. Linear sum assignment requires an incoming and outgoing grouping which is found using the following methodology

       1) First, _split_by_line_id() attempts to use a lines base ID (ID before exploding by circuit), to create groupings, if N/2 lines have the same ID, then there is a clear incoming and outgoing group, else move on to fallback 2.
       2) In the case _split_by_line_id() is unable to find an even split, _split_incoming_outgoing() utilizes the geometry of the lines to find a clear seperation between lines.
       3) In the case that neither method works, it is declared as unmatcheable.

       For nodes of an odd degree, there is an expected leftover line. This line is defined as a tap, and the handedness determined by _handedness, is used to determine what line in the transmission corridor that line taps.

    Parameters
    ----------
    joints_df : pd.DataFrame
        Touch points from 'build_touches()' merged with 'get_line_vector()',
        requiring 'node', 'strand_id', 'id', and 'vector'. 'strand_seq' is
        optional; without it lanes are matched on geometry alone and can swap
        sides across a segment boundary.

    Returns
    -------
    tuple[list[tuple[str, str]], list[tuple[str, str]]]
        An adjacency list, describing line to line connections, and a list containing all tap connections.
    """

    string_edges: list[tuple[str, str]] = []
    tap_edges: list[tuple[str, str]] = []


    for node_id, node_df in joints_df.groupby("node", sort=True):

        # Degree <2: Dead End Checks
        if node_df["id"].nunique() < 2:
            continue

        node_df = node_df.drop_duplicates(subset="strand_id").reset_index(drop=True)
        strand_ids = list(node_df["strand_id"])
        degree = len(strand_ids)

        if degree < 2:
            continue

        # Degree 2: Direct 1-to-1 pass-through vertex
        elif degree == 2:
            string_edges.append(tuple(sorted(strand_ids)))

        # Degree >= 3: Complex Multi-Circuit Junction or T-Tap
        elif degree >= 3:
            vectors = np.vstack(node_df["vector"].values)
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            norm_vectors = vectors / norms

            strand_seqs = (
                list(node_df["strand_seq"])
                if "strand_seq" in node_df.columns
                else None
            )
            line_ids = (
                list(node_df["id"]) if "id" in node_df.columns else None
            )

            pairs, unmatched = _match_strands_at_node(
                strand_ids, norm_vectors, strand_seqs, line_ids
            )
            string_edges.extend(pairs)

            # Unmatched lines occur in nodes of odd degree and trigger the tap assignment logic
            if unmatched:
                virtual_tap_id = f"{_TAP_PREFIX}{node_id}"
                position = {s: i for i, s in enumerate(strand_ids)}

                unmatched_lines = (
                    {line_ids[position[s]] for s in unmatched}
                    if line_ids is not None
                    else {None}
                )

                if len(unmatched_lines) > 1:
                    # Multiple unmatched lines means that the lines at the node could not reconcile
                    # TODO: Add flags for this occurance, and attempt future fixes with extra rules and logic to assign currently unmatchable lines
                    tap_edges.extend((s, virtual_tap_id) for s in strand_ids)
                else:
                    # One line branching off a corridor. It splices onto the lane on its own side
                    for strand_id in unmatched:
                        tap_edges.append((strand_id, virtual_tap_id))

                        lane = _assign_branch_to_lane(
                            position[strand_id], pairs, strand_ids,
                            norm_vectors, strand_seqs,
                        )
                        if lane is not None:
                            tap_edges.extend((s, virtual_tap_id) for s in lane)

    return string_edges, tap_edges



def get_node_df(line_df: pd.DataFrame) -> pd.DataFrame:

    """Generates a node level DataFrame, used primarily for quick access to the degree of each node.

    Parameters
    ----------
    line_df : DataFrame
        A pandas dataframe containing only the transmission lines captured from OSM data,
        requiring 'node_refs' and 'coords'.

    Returns
    -------
    pd.DataFrame
        One row per distinct node with 'node_id', 'coords', and 'degree', where
        degree counts how many lines reference that node.
    """

    node_df = line_df.copy()
    node_df = pd.DataFrame.explode(node_df, ['node_refs', 'coords'])

    node_degree = (
        node_df['node_refs']
        .value_counts()
        .rename_axis('node_refs')
        .reset_index(name='degree')
    )

    nodes = (
        node_df[['node_refs', 'coords']]
        .drop_duplicates(subset='node_refs')
        .rename(columns={'node_refs': 'node_id'})
        .reset_index(drop=True)
    )

    nodes['degree'] = nodes['node_id'].map(node_degree.set_index('node_refs')['degree']).fillna(0).astype(int)
    return nodes


def _union_find(members, links):
    """Union find algorithm used to determine "electrical connectivity" between transmission lines. Each final group
       represents a single continuous conductor between substations or taps.

    Parameters
    ----------
    members : list[str]
        Every strand id to be grouped, including isolated ones that no link
        reaches.
    links : list[tuple[str, str]]
        Strand pairs known to be electrically joined. Sort before passing:
        the smaller id of each merge becomes the group's root, so ordering
        decides the component ids and keeps them stable run to run.

    Returns
    -------
    dict[str, str]
        Each strand id mapped to its group's root id. Strands appearing only
        in 'links' are included alongside those in 'members'.
    """
    parent = {m: m for m in members}

    def _find(x):
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def _union(a, b):
        ra, rb = _find(a), _find(b)
        if ra != rb:
            # Lexicographic min as root keeps component ids reproducable run to run
            parent[max(ra, rb)] = min(ra, rb)

    for a, b in links:
        _union(a, b)

    return {k: _find(k) for k in parent}





def build_circuit_terminals(
    strands: pd.DataFrame,
    strand_links,
    tap_incidence,
    substation_incidence,
) -> pd.DataFrame:

    """Resolves lines into circuits, and create a record of what each circuit is connected to along with other data.

       The culmination of the pipeline; takes pairings and adjacency lists built earlier and uses union find to collapse them into
       components. A circuit electrically connecting two substations is defined as an edge between them. When a circuit
       connects 3 or more substations (due to a t-tap), a tap node is infered and isused to accurately connect all 3
       within a graph network representation.

    
    Parameters
    ----------
    strands : pd.DataFrame
        Exploded strands from 'build_strings()', requiring 'strand_id'.
        'voltage' is optional; without it every circuit reports None rather
        than being flagged mixed.
    strand_links : list[tuple[str, str]]
        Strand pairs running straight through into each other, the first return
        of 'build_string_adjacency_list()'.
    tap_incidence : list[tuple[str, str]]
        (strand_id, junction_id) pairs for strands meeting at a branching
        junction, the second return of 'build_string_adjacency_list()'. Joined
        as a star per junction, so k strands contribute k-1 links rather than
        every pairing.
    substation_incidence : list[tuple[str, str]]
        (strand_id, substation_id) pairs, built in 'GridEngine.run()' from
        'extract_line_substation_connections()'.

    Returns
    -------
    pd.DataFrame
        One row per circuit, keyed by 'component_id'. Carries its members
        ('strands', 'n_strands'), what it reaches ('terminals', 'tap',
        'junctions', and their counts), a 'voltage' where its members agree,
        and the 'is_stub' / 'mixed_voltage' diagnostics.
    """
    
    members = sorted(dict.fromkeys(strands['strand_id']))

    voltage = dict(zip(strands['strand_id'], strands['voltage'])) \
        if 'voltage' in strands.columns else {}

    links = list(strand_links)

    # Strands meeting at a branching junction are conductively joined in a star fashion, not a clique
    by_junction = defaultdict(list)
    for strand_id, junction_id in tap_incidence:
        by_junction[junction_id].append(strand_id)

    for grouped in by_junction.values():
        anchor = grouped[0]
        links.extend((anchor, other) for other in grouped[1:])

    # Group lines into circuits using _union_find()
    parent = _union_find(members, sorted(links))

    comp_strands = defaultdict(list)
    for strand_id in members:
        comp_strands[parent[strand_id]].append(strand_id)

    # Substations reached by each circuit
    comp_substations = defaultdict(set)
    for strand_id, substation_id in substation_incidence:
        if strand_id in parent:
            comp_substations[parent[strand_id]].add(str(substation_id))

    comp_junctions = defaultdict(set)
    for strand_id, junction_id in tap_incidence:
        if strand_id in parent:
            comp_junctions[parent[strand_id]].add(junction_id)

    # Tap Identification
    rows = []
    for component_id in sorted(comp_strands):
        members_here = sorted(comp_strands[component_id])
        substations = tuple(sorted(comp_substations.get(component_id, ())))
        voltages = {voltage.get(s) for s in members_here}
        volt = next(iter(voltages)) if len(voltages) == 1 else None

        # A circuit joining three or more substations is represented as a tap with the following ID
        tap_id = f'{_TAP_PREFIX}{component_id}' if len(substations) >= 3 else None

        terminals = tuple(
            [('substation', s) for s in substations]
            + ([('tap', tap_id)] if tap_id else [])
        )

        #TODO: Make this dynamic so people can add their own features specific to their work, within the engine itself :)
        rows.append({
            'component_id': component_id,
            'voltage': volt,
            'n_strands': len(members_here),
            'strands': tuple(members_here),
            'terminals': terminals,
            'tap': tap_id,
            'junctions': tuple(sorted(comp_junctions.get(component_id, ()))),
            'n_terminals': len(terminals),
            'n_substations': len(substations),
            'n_taps': 1 if tap_id else 0,
            # Diagnostics columns used for downstream reporting
            'is_stub': len(substations) < 2,
            'mixed_voltage': len(voltages) > 1,
        })

    return pd.DataFrame(rows, columns=[
        'component_id', 'voltage', 'n_strands', 'strands', 'terminals', 'tap',
        'junctions', 'n_terminals', 'n_substations', 'n_taps',
        'is_stub', 'mixed_voltage',
    ])




def build_circuit_substation_adjacency(substation_string_adjacency, strings, strand_links):
    """Deprecated: replaced by build_circuit_terminals.

    Kept so existing notebooks keep running. Discards taps and collapses
    parallel circuits, which is why the graph builder no longer uses it.
    """
    #strand_links, _ = partition_adjacency(string_string_adjacency)
    parent = _union_find(sorted(dict.fromkeys(strings['strand_id'])), sorted(strand_links))

    circuit_substation_adjacency = defaultdict(set)

    for strand, substation in substation_string_adjacency:
        if strand in parent:
            circuit_substation_adjacency[parent[strand]].add(substation)

    return circuit_substation_adjacency



def build_strings(line_df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Used to explode transmission corridors, of single voltage, into individual lines based on circuit count.

    Parameters
    ----------
    line_df : gpd.GeoDataFrame
        Single-voltage corridors from 'voltage_splitting()', requiring 'id' and
        'counts'. Rows whose count is missing or below 1 are reported as a
        warning and contribute no strands.

    Returns
    -------
    gpd.GeoDataFrame
        The input repeated once per circuit, with 'strand_seq' numbering the
        lanes within each corridor and 'strand_id' identifying each strand as
        '{id}_s{strand_seq}'.
    """

    for idx, row in line_df.iterrows():
        val = row['counts']
        if pd.isna(val) or not isinstance(val, (int, float)) or val < 1:
            print(f"Warning: Line {row.get('id', idx)} has invalid counts ({val}, type: {type(val).__name__}).")

    strings = line_df.loc[line_df.index.repeat(line_df['counts'])].copy()
    strings['strand_seq'] = strings.groupby('id').cumcount()
    strings['strand_id'] = strings['id'] + '_s' + strings['strand_seq'].astype(str)
    strings = strings.reset_index(drop=True)
    return strings



def build_touches(strings: gpd.GeoDataFrame) -> pd.DataFrame:
    """Record every node each strand terminates at, one row per contact.

    Parameters
    ----------
    strings : gpd.GeoDataFrame
        Exploded strands from 'build_strings()', requiring 'strand_id', 'id',
        'strand_seq', and 'node_refs'.

    Returns
    -------
    pd.DataFrame
        One row per strand endpoint with 'strand_id', 'id', 'strand_seq', and
        'node'. A closed strand contributes one row, not two.
    """

    start_node = strings[['strand_id', 'id', 'strand_seq']].assign(
        node=strings['node_refs'].str[0]
    )

    end_node = strings[['strand_id', 'id', 'strand_seq']].assign(
        node=strings['node_refs'].str[-1]
    )

    touches = pd.concat([start_node, end_node], ignore_index=True)
    touches = touches.drop_duplicates(subset=['strand_id', 'node'])
    return touches