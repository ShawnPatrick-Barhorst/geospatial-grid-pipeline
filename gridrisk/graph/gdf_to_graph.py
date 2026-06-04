import networkx as nx
import geopandas as gpd
from gridrisk.ingestion.cleaning import extract_line_substation_connections


def build_graph_from_gdf(substation_gdf: gpd.GeoDataFrame, line_gdf:gpd.GeoDataFrame, m_buffer=None) -> nx.MultiGraph:
    g = nx.MultiGraph()

    # add substations as nodes
    for idx, row in substation_gdf.iterrows():
        g.add_node(row['id'], 
                   type='substation', 
                   geometry=row['geometry']
                   )

    # create node_refs set
    node_refs = set([node for nodes in line_gdf['node_refs'] for node in nodes])
    # add nodes from node_refs that are not already in the graph
    for node in node_refs:
        g.add_node(node, type='node_ref')

    # add edges from line_gdf
    for idx, row in line_gdf.iterrows():
        node_refs = row['node_refs']
        for i in range(len(node_refs) - 1):
            g.add_edge(node_refs[i], node_refs[i+1], line_id=row['id'], voltage=row['voltage'])

    # add edges from line_substation_mapping
    line_substation_mapping = extract_line_substation_connections(line_gdf, substation_gdf, None)
    for key, value in line_substation_mapping.items():
        node_ref = key
        substation_id = value
        g.add_edge(node_ref, substation_id, type='line_substation_connection')

    return g