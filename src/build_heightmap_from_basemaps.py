#!/usr/bin/env python3
"""Create a 16-bit heightmap from LINZ's Terrain-RGB elevation tiles."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import requests
import yaml
from dotenv import load_dotenv
from PIL import Image
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache" / "linz-terrain-rgb"
OUTPUT = ROOT / "working"
WEB_MERCATOR_WORLD = 40_075_016.68557849
TILE_SIZE = 256


def get_config() -> tuple[float, float, float, float, float]:
    with (ROOT / "config.yaml").open(encoding="utf-8") as file:
        config = yaml.safe_load(file)
    try:
        centre = config["area"]["center"]
        size = config["area"]["size"]
        return (
            float(centre["lat"]),
            float(centre["lng"]),
            float(size["width"]),
            float(size["height"]),
            float(config["heightmap"]["resolution"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("config.yaml must define area.center, area.size, and heightmap.resolution") from error


def cached_tile(url: str, path: Path) -> np.ndarray:
    if not path.exists():
        print(f"Fetching {path.relative_to(CACHE)}")
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
    with Image.open(path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint32)
    # Mapbox Terrain-RGB: height in metres = -10,000 + RGB integer * 0.1.
    return (rgb[..., 0] * 256 * 256 + rgb[..., 1] * 256 + rgb[..., 2]) * 0.1 - 10_000


def main() -> None:
    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("BASEMAPS_API_KEY")
    if not api_key:
        raise RuntimeError("Set BASEMAPS_API_KEY in .env.")

    latitude, longitude, width_m, height_m, resolution = get_config()
    if min(width_m, height_m, resolution) <= 0:
        raise ValueError("Area dimensions and heightmap resolution must be positive.")
    width, height = width_m / resolution, height_m / resolution
    if not width.is_integer() or not height.is_integer():
        raise ValueError("Area dimensions must divide exactly by heightmap.resolution.")
    width, height = int(width), int(height)

    # Choose enough source detail for the requested ground resolution.
    zoom = max(0, math.ceil(math.log2(156543.03392804097 * math.cos(math.radians(latitude)) / resolution)))
    to_nztm = Transformer.from_crs(4326, 2193, always_xy=True)
    to_web_mercator = Transformer.from_crs(2193, 3857, always_xy=True)
    centre_east, centre_north = to_nztm.transform(longitude, latitude)

    east = centre_east + (np.arange(width) + 0.5 - width / 2) * resolution
    north = centre_north + (height / 2 - np.arange(height) - 0.5) * resolution
    source_east, source_north = np.meshgrid(east, north)
    web_x, web_y = to_web_mercator.transform(source_east, source_north)
    tiles_per_side = 2**zoom
    pixel_x = (web_x + WEB_MERCATOR_WORLD / 2) / WEB_MERCATOR_WORLD * tiles_per_side * TILE_SIZE
    pixel_y = (WEB_MERCATOR_WORLD / 2 - web_y) / WEB_MERCATOR_WORLD * tiles_per_side * TILE_SIZE
    tile_x = np.floor(pixel_x / TILE_SIZE).astype(int)
    tile_y = np.floor(pixel_y / TILE_SIZE).astype(int)
    local_x = np.clip(np.floor(pixel_x % TILE_SIZE).astype(int), 0, TILE_SIZE - 1)
    local_y = np.clip(np.floor(pixel_y % TILE_SIZE).astype(int), 0, TILE_SIZE - 1)

    elevations = np.empty((height, width), dtype=np.float64)
    for y in np.unique(tile_y):
        for x in np.unique(tile_x):
            mask = (tile_x == x) & (tile_y == y)
            url = (
                "https://basemaps.linz.govt.nz/v1/tiles/elevation/WebMercatorQuad/"
                f"{zoom}/{x}/{y}.png?api={api_key}&pipeline=terrain-rgb"
            )
            tile = cached_tile(url, CACHE / str(zoom) / str(x) / f"{y}.png")
            elevations[mask] = tile[local_y[mask], local_x[mask]]

    minimum, maximum = float(elevations.min()), float(elevations.max())
    encoded = np.zeros_like(elevations, dtype=np.uint16) if minimum == maximum else np.rint((elevations - minimum) * 65535 / (maximum - minimum)).astype(np.uint16)
    OUTPUT.mkdir(exist_ok=True)
    Image.fromarray(encoded).save(OUTPUT / "heightmap.png")
    (OUTPUT / "heightmap.json").write_text(
        json.dumps(
            {
                "source": "LINZ New Zealand LiDAR 1m DSM (Terrain-RGB)",
                "vertical_datum": "NZVD2016",
                "size_pixels": {"width": width, "height": height},
                "resolution_metres_per_pixel": resolution,
                "elevation_metres": {"minimum": minimum, "maximum": maximum},
                "encoding": "uint16 = (elevation - minimum) / (maximum - minimum) * 65535",
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT / 'heightmap.png'} ({width}x{height}, {minimum:.1f} to {maximum:.1f} m)")


if __name__ == "__main__":
    main()
