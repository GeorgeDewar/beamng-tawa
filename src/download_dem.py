from pathlib import Path
from urllib.parse import urljoin
import json
import requests

nz_elevation = "https://nz-elevation.s3-ap-southeast-2.amazonaws.com"
source = f"{nz_elevation}/wellington/wellington-city_2025/dem_1m/2193"

def cached_get(url: str) -> bytes:
    cache_path = Path("cache/nz-elevation") / Path(url).relative_to(nz_elevation)
    if not cache_path.exists():
        print(f"Fetching {url}")
        response = requests.get(url)
        response.raise_for_status()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(response.content)
    else:
        print(f"Using cached {cache_path}")
    return cache_path.read_bytes()

response = cached_get(source + "/collection.json")
data = json.loads(response.decode("utf-8"))
links = data["links"]
for link in links:
    if link["rel"] not in ("root", "self"):
        url = urljoin(source + "/", link["href"])
        data = json.loads(cached_get(url).decode("utf-8"))
        geotiff_url = urljoin(source + "/", data["assets"]["visual"]["href"])
        cached_get(geotiff_url)
