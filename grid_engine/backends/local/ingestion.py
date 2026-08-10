import osmium as osm
import geopandas as gpd
from shapely.geometry import LineString, Point



class PowerHandler(osm.SimpleHandler):
    """Parses an OSM PBF file to extract power infrastructure data.

    Uses PyOsmium's streaming parser to collect nodes and ways with relevant
    power tags, storing their attributes in structured dictionaries.

    Attributes
    ----------
    nodes : list of dict
        Dictionaries containing attributes of power nodes.
    ways : list of dict
        Dictionaries containing attributes of power ways.

    Notes
    -----
    Must be applied with ``locations=True`` to resolve way node coordinates:

    >>> handler.apply_file("region.osm.pbf", locations=True)

    Examples
    --------
    >>> handler = PowerHandler()
    >>> handler.apply_file("tennessee.osm.pbf", locations=True)
    >>> lines = [w for w in handler.ways if w['type'] == 'line']
    >>> subs = [w for w in handler.ways if w['type'] == 'substation']
    """



    def __init__(self):
        super(PowerHandler, self).__init__()
        self.nodes = []
        self.ways = []

    #TODO: CLean nodes and ways by removing redundant tags and standardizing attributes across types.
    def node(self, n):
        if n.tags.get('power') == 'substation':
            self.nodes.append(
                {
                    'id': n.id,
                    'name': n.tags.get('name'),
                    'type': n.tags.get('power'),
                    'osm_type': 'node',
                    'lat': n.location.lat,
                    'lon': n.location.lon,
                    'elevation': n.tags.get('ele'),
                    'tags': dict(n.tags)
                }
            )

        elif n.tags.get('power') == 'plant':
            self.nodes.append(
                {
                    'id': n.id,
                    'name': n.tags.get('name'),
                    'type': n.tags.get('power'),
                    'osm_type': 'node',
                    'lat': n.location.lat,
                    'lon': n.location.lon,
                    'elevation': n.tags.get('ele'),
                    #'tags': dict(n.tags)
                    'operator': n.tags.get('operator:short') or n.tags.get('operator'),
                    'ref_id': n.tags.get('ref:US:EIA'),
                    'method': n.tags.get('plant:method'),
                    'output': n.tags.get('plant:output:electricity'),
                    'source': n.tags.get('plant:source'), 
                    'storage': n.tags.get('plant:storage'),
                    'start_date': n.tags.get('start_date')
                    
                }
            )
        
        elif n.tags.get('power') == 'portal':
            self.nodes.append(
                {
                    'id': n.id,
                    'name': n.tags.get('name'),
                    'type': n.tags.get('power'),
                    'osm_type': 'node',
                    'lat': n.location.lat,
                    'lon': n.location.lon,
                    'elevation': n.tags.get('ele'),
                    'tags': dict(n.tags),
                }
            )

        elif n.tags.get('power') == 'tower':
            self.nodes.append(
                {
                    'id': n.id,
                    'name': n.tags.get('name'),
                    'type': n.tags.get('power'),
                    'osm_type': 'node',
                    'lat': n.location.lat,
                    'lon': n.location.lon,
                    'elevation': n.tags.get('ele'),
                    'tags': dict(n.tags)
                }
            )

        elif n.tags.get('power') == 'pole':
            self.nodes.append(
                {
                    'id': n.id,
                    'name': n.tags.get('name'),
                    'type': n.tags.get('power'),
                    'osm_type': 'node',
                    'lat': n.location.lat,
                    'lon': n.location.lon,
                    'elevation': n.tags.get('ele'),
                    'tags': dict(n.tags)
                }
            )
            

        elif n.tags.get('power') == 'generator':
            self.nodes.append(
                {
                    'id': n.id,
                    'name': n.tags.get('name'),
                    'type': n.tags.get('power'),
                    'osm_type': 'node',
                    'lat': n.location.lat,
                    'lon': n.location.lon,
                    'elevation': n.tags.get('ele'),

                    # Retrieve generator-specific tags
                    'operator': n.tags.get('operator:short') or n.tags.get('operator'),
                    'generator_method': n.tags.get('generator:method'),
                    'generator_output' : n.tags.get('generator:output:electricity'),
                    'generator_source': n.tags.get('generator:source'),
                    'generator_type': n.tags.get('generator:type'),
                    'manufacturer': n.tags.get('generator:manufacturer'),
                    'model': n.tags.get('manufactrer:type'),
                    'start_date': n.tags.get('start_date')
                }
            )

        elif n.tags.get('power') == 'switch':
            self.nodes.append({
                'id':      n.id,
                'type':    n.tags.get('power'),
                'osm_type': 'node',
                'lat':     n.location.lat,
                'lon':     n.location.lon,
                'name':    n.tags.get('name'),
                'voltage': n.tags.get('voltage'),
            })

        elif n.tags.get('power') == 'compensator':
            self.nodes.append({
                'id':      n.id,
                'type':    n.tags.get('power'),
                'osm_type': 'node',
                'lat':     n.location.lat,
                'lon':     n.location.lon,
                'voltage': n.tags.get('voltage'),
            })

        elif n.tags.get('power') == 'transformer':
            # Already partially collected, ensure voltage is captured
            self.nodes.append({
                'id':        n.id,
                'type':      n.tags.get('power'),
                'osm_type':  'node',
                'lat':       n.location.lat,
                'lon':       n.location.lon,
                'name':      n.tags.get('name'),
                'voltage':   n.tags.get('voltage'),
                'operator':  n.tags.get('operator:short') or n.tags.get('operator'),
            })

    def way(self, w):

        coords = [(n.location.lon, n.location.lat) for n in w.nodes if n.location.valid()]

        if w.tags.get('power') == 'substation' and len(coords) >= 3 and w.is_closed():
            self.ways.append(
                {
                    'id': w.id,
                    'name': w.tags.get('name'),
                    'type': w.tags.get('power'),
                    'voltage': w.tags.get('voltage'),
                    'coords': coords,
                    'node_refs': [n.ref for n in w.nodes],
                    'osm_type': 'way',
                    'tags': dict(w.tags),
                    
                }
            )

        elif w.tags.get('power') == 'line' and len(coords) >= 2:
            self.ways.append(
                {
                    'id': w.id,
                    'name': w.tags.get('name'),
                    'type': w.tags.get('power'),
                    'voltage': w.tags.get('voltage'),
                    'coords': coords,
                    'node_refs': [n.ref for n in w.nodes],
                    'geometry': LineString(coords),
                    'counts': w.tags.get('circuits'),
                    'cables': w.tags.get('cables'),
                    'osm_type': 'way',
                    'tags': dict(w.tags),
                }
            )

        elif w.tags.get('power') == 'minor_line' and len(coords) >= 2:
            self.ways.append(
                {
                    'id': w.id,
                    'name': w.tags.get('name'),
                    'type': w.tags.get('power'),
                    'voltage': w.tags.get('voltage'),
                    'coords': coords,
                    'node_refs': [n.ref for n in w.nodes],
                    'geometry': LineString(coords),
                    'counts': w.tags.get('circuits'),
                    'cables': w.tags.get('cables'),
                    'osm_type': 'way',
                    'tags': dict(w.tags),
                }
            )
        
        elif w.tags.get('power') == 'cable' and len(coords) >= 2:
            self.ways.append(
                {
                    'id': w.id,
                    'name': w.tags.get('name'),
                    'type': w.tags.get('power'),
                    'voltage': w.tags.get('voltage'),
                    'coords': coords,
                    'node_refs': [n.ref for n in w.nodes],
                    'geometry': LineString(coords),
                    'counts': w.tags.get('circuits'),
                    'cables': w.tags.get('cables'),
                    'osm_type': 'way',
                    'tags': dict(w.tags),
                }
            )



def nodes_to_geodataframe(nodes):
    """Converts a list of OSM node dictionaries into a GeoDataFrame.

    Parameters
    ----------
    nodes : list[dict[str, Any]]
        A list of dictionaries representing OSM nodes. Each dictionary 
        must contain ``'lon'`` and ``'lat'`` keys alongside any node attributes.

    Returns
    -------
    geopandas.GeoDataFrame
        A GeoDataFrame with Point geometries in WGS 84 (EPSG:4326) 
        containing all attributes from the input node dictionaries.
    """
    return gpd.GeoDataFrame(
        nodes,
        geometry=[Point(node['lon'], node['lat']) for node in nodes],
        crs='EPSG:4326'
    )

def ways_to_geodataframe(ways):
    """Converts a list of OSM way dictionaries into a GeoDataFrame.

    Parameters
    ----------
    ways : list[dict[str, Any]]
        A list of dictionaries representing OSM ways. Each dictionary 
        must contain a ``'coords'`` key with a sequence of ``(lon, lat)`` 
        coordinate tuples alongside any way attributes.

    Returns
    -------
    geopandas.GeoDataFrame
        A GeoDataFrame with LineString geometries in WGS 84 (EPSG:4326) 
        containing all attributes from the input way dictionaries.
    """
    return gpd.GeoDataFrame(
        ways,
        geometry=[LineString(way['coords']) for way in ways],
        crs='EPSG:4326'
    )

