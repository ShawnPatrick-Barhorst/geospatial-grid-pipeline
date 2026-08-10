import geopandas as gpd
import yaml
from shapely.geometry import LineString, Polygon



def build_toy_data(yaml_path: str) -> gpd.GeoDataFrame:
    """Builds a hand-written test network from YAML, mimicking OSM ingestion output.

    Lets topology scenarios - taps, splices, parallel circuits - be written by
    hand and reasoned about, rather than hunted for in real OSM extracts.

    Parameters
    ----------
    yaml_path : str
        Path to a fixture with two top-level keys. 'substations' entries carry
        'id', 'name', 'type', 'voltage', 'coords', and 'node_refs'; 'powerlines'
        entries carry those minus 'coords', plus 'counts' and a 'geometry'
        mapping holding its own 'coords'. Coordinates are '(lon, lat)' strings.

    Returns
    -------
    gpd.GeoDataFrame
        Substations and powerlines in one frame, with 'coords' parsed to
        (lon, lat) tuples and 'geometry' built as Polygons and LineStrings
        respectively. No CRS is set.
    """

    with open(yaml_path, 'r') as file:
        data = yaml.safe_load(file)

    # Loop through the YAML file creating substations
    substations = []
    for substation in data['substations']:

        coords = []
        for coord in substation['coords']:
            coord = coord.replace('(', '').replace(')', '')
            lon, lat = map(float, coord.split(','))
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
            lon, lat = map(float, coord.split(','))
            coords.append((lon, lat))

        powerline['coords'] = coords
        powerline['geometry'] = LineString(powerline['coords'])
        powerlines.append(powerline)

    
            

    gdf_substations = gpd.GeoDataFrame(substations + powerlines, geometry='geometry')
    return gdf_substations


