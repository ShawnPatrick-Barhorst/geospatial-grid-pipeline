"""Public API gateway for topology functions."""

from grid_engine.backends.local.topology import (segment_ways_at_nodes, 
                                                 extract_line_substation_connections, 
                                                 voltage_splitting, 
                                                 simplify_graph, 
                                                 get_line_vector, 
                                                 build_string_adjacency_list, 
                                                 get_node_df,
                                                 build_circuit_substation_adjacency,
                                                 build_circuit_terminals,
                                                 build_touches,
                                                 build_strings
                                                 )

__all__ = [
    "segment_ways_at_nodes",
    "extract_line_substation_connections",
    "voltage_splitting",
    "simplify_graph",
    "get_line_vector",
    "build_string_adjacency_list",
    "get_node_df",
    "build_circuit_substation_adjacency",
    "build_circuit_terminals",
    "build_touches",
    "build_strings"
]