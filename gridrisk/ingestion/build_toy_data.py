import geopandas as gpd
import yaml
from shapely.geometry import LineString, Polygon

# Each powerline is represented as a dictionary with the following keys:
    # 'id': w.id,
    # 'coords': coords,
    # 'osm_type': 'way',
    # 'type': w.tags.get('power'),
    # 'voltage': w.tags.get('voltage'),
    # 'tags': dict(w.tags),
    # 'name': w.tags.get('name'),
    # 'start_node': w.nodes[0].ref,
    # 'end_node': w.nodes[-1].ref,
    # 'geometry': LineString(coords),
    # 'node_refs': [n.ref for n in w.nodes],
    # 'cables': w.tags.get('cables')

# Each substation is represented as a dictionary with the following keys

    # 'id': w.id,
    # 'osm_type': 'way',
    # 'type': w.tags.get('power'),
    # 'coords': coords,
    # 'name': w.tags.get('name'),
    # 'tags': dict(w.tags),
    # 'voltage': w.tags.get('voltage'),
    # 'node_refs': [n.ref for n in w.nodes],
    # 'geometry': Polygon(coords)


def build_toy_data(yaml_path: str) -> gpd.GeoDataFrame:


    with open(yaml_path, 'r') as file:
        data = yaml.safe_load(file)

    #gdf = gpd.GeoDataFrame()

    # Loop through the YAML file creating substations
    substations = []
    for substation in data['substations']:

        coords = []
        for coord in substation['coords']:
            coord = coord.replace('(', '').replace(')', '')
            lat, lon = map(float, coord.split(','))
            coords.append((lon, lat))

        substation['coords'] = coords
        substation['geometry'] = Polygon(substation['coords'])
        substations.append(substation)


    # Loop through the YAML file creating powerlines
    powerlines = []
    for powerline in data['powerlines']:

        coords = []
        for coord in powerline['geometry']['coords']:
            coord = coord.replace('(', '').replace(')', '')
            lat, lon = map(float, coord.split(','))
            coords.append((lon, lat))

        powerline['coords'] = coords
        powerline['geometry'] = LineString(powerline['coords'])
        powerlines.append(powerline)

    
            

    gdf_substations = gpd.GeoDataFrame(substations + powerlines, geometry='geometry')
    return gdf_substations



    
    