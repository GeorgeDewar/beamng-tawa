#!/usr/bin/env python3
"""Build a base-texture PNG by stitching LINZ aerial imagery tiles."""

from __future__ import annotations

import math
import os
from pathlib import Path

import numpy as np
import requests
from dotenv import load_dotenv
from PIL import Image
from pyproj import Transformer
from config import Config

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache" / "linz-aerial-imagery"
OUTPUT = ROOT / "working"
WEB_MERCATOR_WORLD = 40_075_016.68557849
TILE_SIZE = 256


def cached_tile(url: str, path: Path) -> np.ndarray:
    """Return an RGB aerial tile, downloading it once when it is not cached."""
    if not path.exists():
        print(f"Fetching {path.relative_to(CACHE)}")
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8)


def main() -> None:
    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("BASEMAPS_API_KEY")
    if not api_key:
        raise RuntimeError("Set BASEMAPS_API_KEY in .env.")

    config = Config()
    latitude, longitude = config.get_area_center()
    base_texture = config.data["base_texture"]
    resolution = float(base_texture["resolution"])
    area_width, area_height = config.get_area_size()
    if not all(math.isfinite(value) for value in (latitude, longitude, resolution, area_width, area_height)):
        raise ValueError("Base-texture coordinates, dimensions, and resolution must be finite.")
    if min(resolution, area_width, area_height) <= 0:
        raise ValueError("Base-texture dimensions and resolution must be positive.")
    texture_width, texture_height = area_width / resolution, area_height / resolution
    if not texture_width.is_integer() or not texture_height.is_integer():
        raise ValueError("Area dimensions must divide exactly by base_texture.resolution.")
    texture_width, texture_height = int(texture_width), int(texture_height)

    # Choose enough source detail for the requested ground resolution.
    zoom = max(0, math.ceil(math.log2(156543.03392804097 * math.cos(math.radians(latitude)) / resolution)))
    print(f"Using zoom level {zoom} for base texture resolution {resolution} m/pixel")
    to_nztm = Transformer.from_crs(4326, 2193, always_xy=True)
    to_web_mercator = Transformer.from_crs(2193, 3857, always_xy=True)
    centre_east, centre_north = to_nztm.transform(longitude, latitude)

    east = centre_east + (np.arange(texture_width) + 0.5 - texture_width / 2) * resolution
    north = centre_north + (texture_height / 2 - np.arange(texture_height) - 0.5) * resolution
    source_east, source_north = np.meshgrid(east, north)
    web_x, web_y = to_web_mercator.transform(source_east, source_north)
    tiles_per_side = 2**zoom
    pixel_x = (web_x + WEB_MERCATOR_WORLD / 2) / WEB_MERCATOR_WORLD * tiles_per_side * TILE_SIZE
    pixel_y = (WEB_MERCATOR_WORLD / 2 - web_y) / WEB_MERCATOR_WORLD * tiles_per_side * TILE_SIZE
    tile_x = np.floor(pixel_x / TILE_SIZE).astype(int)
    tile_y = np.floor(pixel_y / TILE_SIZE).astype(int)
    local_x = np.clip(np.floor(pixel_x % TILE_SIZE).astype(int), 0, TILE_SIZE - 1)
    local_y = np.clip(np.floor(pixel_y % TILE_SIZE).astype(int), 0, TILE_SIZE - 1)

    # The individual Web Mercator tiles are sampled into one image in the
    # requested NZTM-aligned output grid.  This preserves the configured
    # dimensions while hiding every tile boundary in the final texture.
    texture = np.empty((texture_height, texture_width, 3), dtype=np.uint8)
    for y in np.unique(tile_y):
        for x in np.unique(tile_x):
            mask = (tile_x == x) & (tile_y == y)
            url = (
                f"https://basemaps.linz.govt.nz/v1/tiles/aerial/WebMercatorQuad/{zoom}/{x}/{y}.png?api={api_key}"
            )
            tile = cached_tile(url, CACHE / str(zoom) / str(x) / f"{y}.png")
            texture[mask] = tile[local_y[mask], local_x[mask]]

    OUTPUT.mkdir(exist_ok=True)
    output_path = OUTPUT / "base_texture.png"
    Image.fromarray(texture, mode="RGB").save(output_path)
    print(f"Wrote {output_path} ({texture_width}x{texture_height})")


if __name__ == "__main__":
    main()
