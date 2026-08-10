import networkx as nx
import matplotlib.pyplot as plt
from collections import defaultdict



def build_networkx_graph(circuit_terminals, substation_attrs={}, tap_attrs={}) -> nx.MultiGraph:
    """Renders circuit terminals into a NetworkX MultiGraph modeling electrical connectivity.

    Direct edges connect 2-substation circuits; circuits with 3+ substations 
    use a central tap node. Components with <2 substations are logged in 
    ``G.graph['dropped_components']``.

    Parameters
    ----------
    circuit_terminals : pandas.DataFrame
        Circuit records containing 'component_id', 'terminals', and optional 'tap'.
    substation_attrs : dict, optional
        Extra attributes keyed by substation ID, by default {}
    tap_attrs : dict, optional
        Extra attributes keyed by tap ID, by default {}

    Returns
    -------
    networkx.MultiGraph
        Graph with 'substation' and 'tap' nodes connected by circuit edges.
    """
    G = nx.MultiGraph()
    dropped = []

    for row in circuit_terminals.to_dict('records'):
        component_id = row['component_id']
        substations = [tid for kind, tid in row['terminals'] if kind == 'substation']

        # Check for NaN, None, etc
        tap_id = row.get('tap')
        if not isinstance(tap_id, str):
            tap_id = None

        # Record dead ends for down-stream analysis
        if len(substations) < 2:
            dropped.append(component_id)
            continue

        base = {
            'component': component_id,
            'circuit': component_id,
            'voltage': row.get('voltage'),
            'strands': row.get('strands', ()),
            'n_strands': row.get('n_strands', 0),
        }

        for substation_id in substations:
            G.add_node(
                substation_id,
                node_type='substation',
                **substation_attrs.get(substation_id, {}),
            )

        if tap_id is None:
            u, v = substations
            G.add_edge(u, v, key=component_id, shape='direct', **base)
            continue

        # Add Tap Nodes explicitly
        G.add_node(
            tap_id,
            node_type='tap',
            circuit=component_id,
            voltage=row.get('voltage'),
            junctions=row.get('junctions', ()),
            **tap_attrs.get(tap_id, {}),
        )
        for substation_id in substations:
            G.add_edge(
                tap_id, substation_id,
                key=f"{component_id}@{substation_id}",
                shape='tap', hub=tap_id, **base,
            )

    G.graph['dropped_components'] = dropped
    return G



#TODO(AI Placeholder): Replace this function with something that actually looks nice and is clean. Really only useable for test cases.
def view_networkx_graph(G: nx.MultiGraph):
    # 1. Compute node positions using spring_layout
    pos = nx.spring_layout(G, seed=42)

    # 2. Draw nodes first, keeping taps visually distinct from substations
    taps = [n for n, d in G.nodes(data=True) if d.get("node_type") == "tap"]
    substations = [n for n in G.nodes() if n not in set(taps)]

    nx.draw_networkx_nodes(
        G, pos, nodelist=substations, node_size=1000,
        node_color="mediumseagreen", node_shape="o",
    )
    nx.draw_networkx_nodes(
        G, pos, nodelist=taps, node_size=400,
        node_color="darkorange", node_shape="^",
    )
    nx.draw_networkx_labels(G, pos, font_size=7)

    # 3. Group multi-edges between the same node pairs
    # We need to assign a unique arc radius to each edge key
    edge_groups = {}
    for u, v, k in G.edges(keys=True):
        # Ensure (u, v) and (v, u) share the same group key
        pair = tuple(sorted([u, v]))
        if pair not in edge_groups:
            edge_groups[pair] = []
        edge_groups[pair].append(k)

    # 4. Draw edges with dynamic curvature based on their index
    for (u, v), keys in edge_groups.items():
        num_edges = len(keys)

        for i, key in enumerate(keys):
            # If there's only 1 edge, draw a straight line (rad = 0.0)
            if num_edges == 1:
                rad = 0.0
            else:
                # Spread radii symmetrically: e.g., -0.2, 0.2 or -0.3, 0.0, 0.3
                rad = 0.15 * (i - (num_edges - 1) / 2)

            # Get edge attributes (like voltage for color). Voltage arrives as
            # integer volts from clean_voltages, not a "500kV" style string.
            edge_data = G[u][v][key]
            try:
                voltage = int(edge_data.get("voltage"))
            except (TypeError, ValueError):
                voltage = None
            color = "darkred" if voltage is not None and voltage >= 500000 else "steelblue"

            # Draw this specific edge with its unique curve radius
            nx.draw_networkx_edges(
                G,
                pos,
                edgelist=[(u, v)],
                edge_color=color,
                width=2.5,
                connectionstyle=f"arc3, rad={rad}",
            )

    plt.axis("off")
    plt.show()