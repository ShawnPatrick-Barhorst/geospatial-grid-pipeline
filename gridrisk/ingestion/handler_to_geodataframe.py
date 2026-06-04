import geopandas as gpd
from shapely.geometry import Point, LineString

def nodes_to_geodataframe(nodes):
    return gpd.GeoDataFrame(
        nodes,
        geometry=[Point(node['lon'], node['lat']) for node in nodes],
        crs='EPSG:4326'
    )

def ways_to_geodataframe(ways):
    return gpd.GeoDataFrame(
        ways,
        geometry=[LineString(way['coords']) for way in ways],
        crs='EPSG:4326'
    )