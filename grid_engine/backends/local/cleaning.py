from __future__ import annotations

import geopandas as gpd
import pandas as pd
import numpy as np

import re
import math

# TODO: _LINE_TYPES is duplicated both here and in topology creating 2 truths that need updated, create a single source instead.
_LINE_TYPES = {"line", "minor_line", "cable"}


def clean_voltages(v):
    """Cleans and standardizes raw OSM voltage values into volts.

    Parses multi-value delimited strings (e.g., ``"10kV; 20kV"``) or single 
    numeric values, converting them into a list of integer volt values.

    Parameters
    ----------
    v : str, int, float, or None
        Raw voltage tag from OSM data.

    Returns
    -------
    list of int or None
        Extracted voltages in volts, or ``None`` if the input is missing 
        or invalid.
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
        return voltages

    else:
        return None



#TODO: Add cross referencing across lines with shared corridors, 
# (ex: line_a and line_b shared the same corridor and together have 3 circuits, 
# after propagate_circuit_counts we know that line_a has 2 of the 3 circuits, 
# implying that line_b has 1 circuit)
def propagate_circuit_counts(lines_df: gpd.GeoDataFrame, max_iterations: int = 100) -> gpd.GeoDataFrame:
    """Propagates circuit counts along connected two degree endpoints.

    Sorts lines with degree 2 nodes into 3 buckets:
        **Bucket 1:** Both of lines neighbors have recorded circuit counts
        **Bucket 2:** Only one of the lines neighbors have recorded circuit counts
        **Bucket 3:** Neither of the lines neighbors have recorded circuit counts

    The algorithm ignores Bucket 1 and iterates over bucket 2, propagating circuit counts to neighbors whilst simultaneously moving
    lines from Bucket 3 into Bucket 2 as neighbors are updated. This process repeats until Bucket 2 is empty OR max_iterations is met.

    This may leave some lines in bucket 3 which are impossible to impute unless this algorithm is updated.

    Parameters
    ----------
    lines_df : gpd.GeoDataFrame
        Transmission corridors, requiring 'id', 'counts', and 'node_refs'.
        Counts that cannot be coerced to a number are treated as missing and
        become candidates for imputation.
    max_iterations : int, optional
        Cap on propagation passes, by default 100. Values of 0 or below fall
        back to 999. Propagation stops early once a pass resolves nothing.

    Returns
    -------
    gpd.GeoDataFrame
        A copy of 'lines_df' with 'counts' filled where propagation reached,
        'id' cast to str, and a 'confidence' column marking imputed counts
        'anchored'. Every other row is marked 'unresolved', including lines
        whose counts came from OSM and never needed imputing.
    """
    lines_df = lines_df.copy()

    lines_df['id'] = lines_df['id'].astype(str)
    lines_df['counts'] = pd.to_numeric(lines_df['counts'], errors='coerce')

    # Create confidence column to identify imputed counts downstream
    if 'confidence' not in lines_df.columns:
        lines_df['confidence'] = pd.NA

    # Identify passable degree-2 nodes directly from active lines_df endpoints
    all_endpoints = pd.concat([
        lines_df['node_refs'].str[0],
        lines_df['node_refs'].str[-1]
    ])
    ep_counts = all_endpoints.value_counts()
    passable_nodes = set(ep_counts[ep_counts == 2].index)

    for iteration in range(max_iterations if max_iterations > 0 else 999):

        if not lines_df['counts'].isna().any():
            break

        endpoints = pd.concat([
            lines_df[['id']].assign(node=lines_df['node_refs'].str[0]),
            lines_df[['id']].assign(node=lines_df['node_refs'].str[-1]),
        ])
        endpoints = endpoints[endpoints['node'].isin(passable_nodes)]

        pairs = endpoints.merge(endpoints, on='node', suffixes=('_a', '_b'))
        pairs = pairs[pairs['id_a'] != pairs['id_b']]

        pairs = pairs.merge(lines_df[['id', 'counts']], left_on='id_b', right_on='id')

        valid_pairs = pairs.dropna(subset=['counts'])
        if valid_pairs.empty:
            break

        # Group by target Line A ID
        resolved = (
            valid_pairs
            .groupby('id_a')['counts']
            .agg(lambda s: s.iloc[0] if s.nunique() == 1 else np.nan)
            .dropna()
        )

        # Ensure we only update lines that currently have NaN counts
        unresolved_mask = lines_df['counts'].isna()
        unresolved_ids = set(lines_df.loc[unresolved_mask, 'id'])
        resolved = resolved[resolved.index.isin(unresolved_ids)]

        if resolved.empty:
            break

        resolved_dict = resolved.to_dict()
        mask = lines_df['id'].isin(resolved_dict.keys())
        
        lines_df.loc[mask, 'counts'] = lines_df.loc[mask, 'id'].map(resolved_dict)
        lines_df.loc[mask, 'confidence'] = 'anchored'

    lines_df['confidence'] = lines_df['confidence'].fillna('unresolved')
    return lines_df