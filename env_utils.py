from __future__ import annotations

import json
import time
import folium
import requests
from shapely.geometry import shape, Point
from shapely.ops import transform
from pyproj import Transformer, CRS

OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",  # Moved to front (more reliable)
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]


def get_coordinates(address) -> tuple[float, float]:
    r = requests.get(
        "https://photon.komoot.io/api/",
        params={"q": address, "limit": 1},
        headers={"User-Agent": "building-footprint-lookup/1.0"}
    )
    r.raise_for_status()
    
    results = r.json().get("features", [])
    
    if not results:
        raise ValueError(f"Address not found: {address}")
    
    result = results[0]
    lon, lat = result["geometry"]["coordinates"]
    
    print(f"Found: {result['properties'].get('name', address)}")
    print(f"Coordinates: {lat}, {lon}")
    
    time.sleep(0.5)
    return lat, lon


def build_overpass_query(lat, lon, delta=0.002) -> str:
    """Build Overpass QL query for buildings in bounding box."""
    bbox = f"{lat-delta},{lon-delta},{lat+delta},{lon+delta}"
    return f"""[out:json];
(
  way["building"]({bbox});
  relation["building"]({bbox});
);
out geom;"""


def fetch_overpass_data(query, max_retries=3) -> dict | None:
    """Fetch data from Overpass with retry logic."""
    data = None
    for url in OVERPASS_URLS:
        print(f"\nTrying {url}...")
        
        for attempt in range(max_retries):
            try:
                print(f"  Attempt {attempt + 1}/{max_retries}...")
                r = requests.post(
                    url,
                    data=query,
                    timeout=60,
                    headers={"User-Agent": "building-footprint-lookup/1.0"}
                )
                r.raise_for_status()
                data = r.json()
                print(f"  Success!")
                break
            
            except requests.exceptions.Timeout:
                wait_time = 2 ** attempt
                print(f"  Timeout, waiting {wait_time}s...")
                time.sleep(wait_time)
            
            except requests.exceptions.ConnectionError:
                wait_time = 2 ** attempt
                print(f"  Connection error, waiting {wait_time}s...")
                time.sleep(wait_time)
            
            except requests.exceptions.HTTPError as e:
                if e.response.status_code in [403, 429]:
                    print(f"  HTTP {e.response.status_code}: Rate limited.")
                    break
                elif e.response.status_code in [503, 504]:
                    wait_time = 2 ** attempt
                    print(f"  HTTP {e.response.status_code}, waiting {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    print(f"  HTTP {e.response.status_code}")
                    break
            
            except json.JSONDecodeError:
                print(f"  Invalid JSON response")
                break
        
        else:
            continue
        
        if data and data.get("elements"):
            break
        
        time.sleep(2)
    
    return data


def extract_building_geometry(element) -> tuple[shape | None, dict | None]:
    geom = None
    geom_dict = None
    
    if element["type"] == "way" and "geometry" in element:
        coords = [[node["lon"], node["lat"]] for node in element["geometry"]]
        if len(coords) >= 3:
            geom_dict = {"type": "Polygon", "coordinates": [coords]}
            geom = shape(geom_dict)
    
    elif element["type"] == "relation" and "members" in element:
        outer_coords = []
        for member in element["members"]:
            if member.get("type") == "way" and member.get("role") in ["outer", ""]:
                if "geometry" in member:
                    coords = [[node["lon"], node["lat"]] for node in member["geometry"]]
                    outer_coords.extend(coords)
        
        if len(outer_coords) >= 3:
            geom_dict = {"type": "Polygon", "coordinates": [outer_coords]}
            geom = shape(geom_dict)
    
    return geom, geom_dict


def create_feature(element, geom_dict) -> dict:
    """Create GeoJSON feature from element."""
    return {
        "geometry": geom_dict,
        "properties": element.get("tags", {}),
        "id": element.get("id")
    }


def get_building_footprint(address, max_retries=3) -> tuple[dict | None, float, float]:
    lat, lon = get_coordinates(address)
    point = Point(lon, lat)
    
    query = build_overpass_query(lat, lon)
    data = fetch_overpass_data(query, max_retries)
    
    if not data or not data.get("elements"):
        print("No buildings found in this area.")
        return None, lat, lon
    
    closest_building = None
    closest_distance = float('inf')
    
    for element in data["elements"]:
        if element["type"] not in ["way", "relation"]:
            continue
        
        try:
            geom, geom_dict = extract_building_geometry(element)
            
            if geom:
                distance = geom.distance(point)
                
                if distance < 0.0001:
                    print("Building found")
                    return create_feature(element, geom_dict), lat, lon
                
                if distance < closest_distance:
                    closest_distance = distance
                    closest_building = create_feature(element, geom_dict)
                    closest_building["distance_m"] = distance * 111000
        
        except Exception as e:
            print(f"Error processing element: {e}")
            continue
    
    if closest_building:
        dist_m = closest_building["distance_m"]
        name = closest_building['properties'].get('name', 'Unknown')
        print(f"No exact match. Closest: {name} ({dist_m:.1f}m away)")
        if dist_m > 100:
            print(f"WARNING: Building is {dist_m:.0f}m away.")
        return closest_building, lat, lon
    
    print("No building found in this area.")
    return None, lat, lon


def get_polygon_area(feature) -> float:
    polygon = shape(feature["geometry"])
    lon, lat = polygon.centroid.x, polygon.centroid.y

    utm_crs = CRS.from_dict({
        "proj": "utm",
        "zone": int((lon + 180) / 6) + 1,
        "south": lat < 0
    })

    transformer = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
    projected = transform(transformer.transform, polygon)

    return projected.area


def get_building_map(footprint_geojson) -> folium.Map:
    geom = shape(footprint_geojson["geometry"])
    lat, lon = geom.centroid.y, geom.centroid.x

    map = folium.Map(
        location=[lat, lon], 
        zoom_start=18,
        tiles='CartoDB positron'
    )
    folium.GeoJson(data={
        "type": "Feature",
        "geometry": footprint_geojson["geometry"],
        "properties": footprint_geojson.get("properties", {})
    }).add_to(map)

    return map
