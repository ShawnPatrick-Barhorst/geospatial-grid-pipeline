import pandas as pd

from grid_engine.cleaning import clean_voltages, propagate_circuit_counts
from grid_engine.topology import segment_ways_at_nodes, voltage_splitting, get_node_df
from grid_engine.topology import get_line_vector, build_string_adjacency_list
from grid_engine.topology import build_strings, build_touches
from grid_engine.topology import extract_line_substation_connections
from grid_engine.topology import build_circuit_terminals
from grid_engine.graph import build_networkx_graph, view_networkx_graph

class GridEngine:

    """Runs the full OSM-to-circuit-graph pipeline and retains its intermediates.

    Parameters
    ----------
    lines_gdf : gpd.GeoDataFrame
        Transmission corridors from ingestion, requiring 'id', 'type',
        'voltage', 'counts', 'node_refs', 'coords', and 'geometry'.
    substations_gdf : gpd.GeoDataFrame
        Substations, requiring 'id' and 'geometry'.
    m_buffer : int, optional
        Search distance in meters for line endpoints that miss a substation,
        by default 50.
    verbose : bool, optional
        Unused, by default False.
    voltage_selection : list[int], optional
        Voltages to keep after splitting, by default None (keep all).
    """

    def __init__(self, lines_gdf, substations_gdf, m_buffer=50, verbose=False, voltage_selection=None):
        self.lines_df = lines_gdf
        self.substations_gdf = substations_gdf

        self.m_buffer = m_buffer

        self.networkx_graph = None
        self.voltage_selection = voltage_selection

        self.substation_line_adjacency = None
        self.string_string_adjacency = None
        self.substation_string_adjacency = None
        self.circuit_terminals = None
        self.dropped_components = None

    def run(self):
        """Executes the pipeline, storing the graph and every intermediate on self.

        Cleans voltages, segments corridors at shared nodes, explodes them by
        voltage and circuit count, matches strands into circuits at each node,
        attaches substations, and renders the result as a MultiGraph.

        Inputs are copied, so the caller's frames are never mutated. Results
        land on 'networkx_graph', 'circuit_terminals', and the adjacency
        attributes; nothing is returned.
        """
        # 1. Make a fresh copy so we don't mutate the user's raw input data
        line_gdf = self.lines_df.copy()
        substation_gdf = self.substations_gdf.copy()

        # 2. Cleaning & Topology Preprocessing
        line_gdf['voltage'] = line_gdf['voltage'].apply(clean_voltages)
        line_gdf = segment_ways_at_nodes(line_gdf)
        line_gdf = voltage_splitting(line_gdf)
        if self.voltage_selection is not None:
            line_gdf = line_gdf[line_gdf['voltage'].isin(self.voltage_selection)]

        new_lines_df = propagate_circuit_counts(line_gdf)

        #TODO: Replace with function that drops lines where all nodes map to the same substation ID (i.e. internal intra-substation lines)
        new_lines_df = new_lines_df.dropna(subset=['counts']).copy()

        # 3. Strand Explosion & Touch Points
        strings = build_strings(new_lines_df)
        touches = build_touches(strings)
        touches = touches.merge(get_line_vector(new_lines_df), on=['id', 'node'], how='left')
        string_edges, tap_edges = build_string_adjacency_list(touches)

        # 4. Substation Connections
        substation_line_adjacency = extract_line_substation_connections(
            new_lines_df, 
            substation_gdf, 
            m_buffer=self.m_buffer
        )

        touches['substation_id'] = touches['node'].map(substation_line_adjacency)
        substation_touches = touches.dropna(subset=['substation_id']).copy()
        # Int64 round-trip, not a bare .replace('.0', ...) - that is unanchored
        # and would corrupt any id containing '.0' mid-string.
        substation_touches['substation_id'] = (
            pd.to_numeric(substation_touches['substation_id'], errors='coerce')
            .astype('Int64')
            .astype(str)
        )


        substation_string_adjacency = list(
            zip(substation_touches['strand_id'], substation_touches['substation_id'])
        )


        # 5. Resolve circuits and their terminals (substations AND taps)
        circuit_terminals = build_circuit_terminals(
            strings,
            string_edges,
            tap_edges,
            substation_string_adjacency,
        )

        # 6. Render the graph
        G = build_networkx_graph(circuit_terminals)

        self.networkx_graph = G

        # 7. Store intermediates for inspection
        self.substation_line_adjacency = substation_line_adjacency
        self.string_string_adjacency = string_edges
        self.tap_edges = tap_edges
        self.substation_string_adjacency = substation_string_adjacency
        self.circuit_terminals = circuit_terminals
        self.dropped_components = G.graph.get('dropped_components', [])

    def view(self):
        view_networkx_graph(self.networkx_graph)