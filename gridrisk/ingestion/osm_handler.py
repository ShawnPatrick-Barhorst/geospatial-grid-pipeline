import osmium as osm
from shapely.geometry import LineString


class PowerHandler(osm.SimpleHandler):
    """Parses an OSM PBF file to extract power infrastructure data.

    Parses an OSM PBF file using PyOsmium's streaming parser to 
    extract power infrastructure data. It collects nodes and ways with
    relevant power tags, storing their attributes in structured dictionaries.

    Must be applied with locations=True to resolve way node coordinates:
    handler.apply_file("region.osm.pbf", locations=True)

    Attributes:
        nodes: List of dictionaries containing attributes of power nodes.
        ways: List of dictionaries containing attributes of power ways.

    
    Example: 
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
                    'osm_type': 'way',
                    'type': w.tags.get('power'),
                    'coords': coords,
                    'name': w.tags.get('name'),
                    'tags': dict(w.tags),
                    'node_refs': [n.ref for n in w.nodes]
                }
            )

        elif w.tags.get('power') == 'line' and len(coords) >= 2:
            self.ways.append(
                {
                    'id': w.id,
                    'coords': coords,
                    'osm_type': 'way',
                    'type': w.tags.get('power'),
                    'tags': dict(w.tags),
                    'name': w.tags.get('name'),
                    'start_node': w.nodes[0].ref,
                    'end_node': w.nodes[-1].ref,
                    'geometry': LineString(coords),
                    'node_refs': [n.ref for n in w.nodes]
                }
            )

        elif w.tags.get('power') == 'minor_line' and len(coords) >= 2:
            self.ways.append(
                {
                    'id': w.id,
                    'coords': coords,
                    'osm_type': 'way',
                    'type': w.tags.get('power'),
                    'tags': dict(w.tags),
                    'name': w.tags.get('name'),
                    'start_node': w.nodes[0].ref,
                    'end_node': w.nodes[-1].ref,
                    'geometry': LineString(coords),
                    'node_refs': [n.ref for n in w.nodes]
                }
            )
        
        elif w.tags.get('power') == 'cable' and len(coords) >= 2:
            self.ways.append(
                {
                    'id': w.id,
                    'coords': coords,
                    'osm_type': 'way',
                    'type': w.tags.get('power'),
                    'tags': dict(w.tags),
                    'name': w.tags.get('name'),
                    'start_node': w.nodes[0].ref,
                    'end_node': w.nodes[-1].ref,
                    'geometry': LineString(coords),
                    'node_refs': [n.ref for n in w.nodes]
                }
            )


        