#!/usr/bin/env python3
"""Build a 16-bit grayscale heightmap from LINZ Wellington City DEM GeoTIFFs."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import yaml
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache" / "nz-elevation"
WORKING = ROOT / "working"
COLLECTION_URL = (
    "https://nz-elevation.s3-ap-southeast-2.amazonaws.com/"
    "wellington/wellington-city_2025/dem_1m/2193/collection.json"
)
REQUIRED_GDAL_COMMANDS = ("gdalbuildvrt", "gdalwarp", "gdalinfo", "gdal_translate")


def read_config() -> tuple[float, float, float, float, int, int]:
    """Return the centre in NZTM coordinates and exact output dimensions."""
    with (ROOT / "config.yaml").open(encoding="utf-8") as file:
        config = yaml.safe_load(file)

    try:
        center = config["area"]["center"]
        size = config["area"]["size"]
        latitude = float(center["lat"])
        longitude = float(center["lng"])
        width_m = float(size["width"])
        height_m = float(size["height"])
        resolution = float(config["heightmap"]["resolution"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(
            "config.yaml must define area.center, area.size, and heightmap.resolution."
        ) from error

    if not all(math.isfinite(value) for value in (latitude, longitude, width_m, height_m, resolution)):
        raise ValueError("All config.yaml coordinates, dimensions, and resolution values must be finite.")
    if min(width_m, height_m, resolution) <= 0:
        raise ValueError("Area dimensions and heightmap resolution must be positive.")

    output_width = width_m / resolution
    output_height = height_m / resolution
    if not output_width.is_integer() or not output_height.is_integer():
        raise ValueError("Area dimensions must divide exactly by heightmap.resolution.")

    to_nztm = Transformer.from_crs(4326, 2193, always_xy=True)
    centre_x, centre_y = to_nztm.transform(longitude, latitude)
    return centre_x, centre_y, width_m, height_m, int(output_width), int(output_height)


def required_commands() -> None:
    missing = [command for command in REQUIRED_GDAL_COMMANDS if shutil.which(command) is None]
    if missing:
        raise RuntimeError(f"GDAL command(s) not found on PATH: {', '.join(missing)}")


def cache_path(url: str) -> Path:
    """Map an elevation-service URL to a workspace cache path."""
    parsed = urlparse(url)
    return CACHE / parsed.netloc / parsed.path.lstrip("/")


def download(url: str) -> Path:
    """Return a cached copy of a remote resource, downloading it if necessary."""
    path = cache_path(url)
    if path.exists() and path.stat().st_size > 0:
        print(f"Using cached {path.relative_to(ROOT)}")
        return path

    print(f"Downloading {url}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".part")
    try:
        with requests.get(url, stream=True, timeout=(30, 600)) as response:
            response.raise_for_status()
            with temporary_path.open("wb") as file:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        file.write(chunk)
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return path


def requested_geographic_bounds(
    centre_x: float, centre_y: float, width_m: float, height_m: float
) -> tuple[float, float, float, float]:
    """Convert the four NZTM area corners to a conservative WGS84 bounding box."""
    to_wgs84 = Transformer.from_crs(2193, 4326, always_xy=True)
    half_width = width_m / 2
    half_height = height_m / 2
    corners = (
        (centre_x - half_width, centre_y - half_height),
        (centre_x - half_width, centre_y + half_height),
        (centre_x + half_width, centre_y - half_height),
        (centre_x + half_width, centre_y + half_height),
    )
    longitudes, latitudes = zip(*(to_wgs84.transform(x, y) for x, y in corners))
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


def intersects(
    left: tuple[float, float, float, float], right: tuple[float, float, float, float]
) -> bool:
    """Return whether two WGS84 bounding boxes overlap."""
    return not (left[2] < right[0] or left[0] > right[2] or left[3] < right[1] or left[1] > right[3])


def download_source_tiffs(bounds: tuple[float, float, float, float]) -> list[Path]:
    """Download only collection assets whose STAC bounding boxes overlap the area."""
    collection = json.loads(download(COLLECTION_URL).read_text(encoding="utf-8"))
    item_urls = [
        urljoin(COLLECTION_URL, link["href"])
        for link in collection["links"]
        if link.get("rel") == "item"
    ]

    tiffs: list[Path] = []
    for item_url in item_urls:
        item = json.loads(download(item_url).read_text(encoding="utf-8"))
        try:
            west, south, east, north = (float(value) for value in item["bbox"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"STAC item {item_url} has an invalid bounding box.") from error
        item_bounds = (west, south, east, north)
        if not intersects(bounds, item_bounds):
            continue
        try:
            asset_url = urljoin(item_url, item["assets"]["visual"]["href"])
        except KeyError as error:
            raise ValueError(f"STAC item {item_url} has no visual GeoTIFF asset.") from error
        tiffs.append(download(asset_url))

    if not tiffs:
        raise RuntimeError("The requested area does not intersect any GeoTIFF in the DEM collection.")
    return tiffs


def run_gdal(*arguments: str) -> None:
    print(" ".join(arguments))
    subprocess.run(arguments, check=True)


def elevation_range(path: Path) -> tuple[float, float]:
    """Read GDAL-computed valid elevation statistics for the cropped raster."""
    completed = subprocess.run(
        ("gdalinfo", "-json", "-stats", str(path)),
        check=True,
        capture_output=True,
        text=True,
    )
    band = json.loads(completed.stdout)["bands"][0]
    try:
        minimum = float(band["minimum"])
        maximum = float(band["maximum"])
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError(f"GDAL could not determine valid elevation statistics for {path}.") from error
    if not math.isfinite(minimum) or not math.isfinite(maximum):
        raise RuntimeError("The cropped elevation raster contains no valid samples.")
    return minimum, maximum


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep-intermediate",
        action="store_true",
        help="Keep the intermediate source mosaic in working/.",
    )
    args = parser.parse_args()

    required_commands()
    centre_x, centre_y, width_m, height_m, width_px, height_px = read_config()
    geographic_bounds = requested_geographic_bounds(centre_x, centre_y, width_m, height_m)
    source_tiffs = download_source_tiffs(geographic_bounds)

    WORKING.mkdir(exist_ok=True)
    mosaic = WORKING / "dem-mosaic.vrt"
    elevation_tiff = WORKING / "elevation.tiff"
    heightmap = WORKING / "heightmap.png"

    run_gdal("gdalbuildvrt", "-overwrite", "-resolution", "highest", str(mosaic), *(str(path) for path in source_tiffs))

    half_width = width_m / 2
    half_height = height_m / 2
    run_gdal(
        "gdalwarp",
        "-overwrite",
        "-r",
        "bilinear",
        "-te",
        str(centre_x - half_width),
        str(centre_y - half_height),
        str(centre_x + half_width),
        str(centre_y + half_height),
        "-ts",
        str(width_px),
        str(height_px),
        "-t_srs",
        "EPSG:2193",
        "-of",
        "GTiff",
        "-co",
        "COMPRESS=DEFLATE",
        "-co",
        "TILED=YES",
        str(mosaic),
        str(elevation_tiff),
    )

    minimum, maximum = elevation_range(elevation_tiff)
    scale = ("0", "0", "0", "0") if minimum == maximum else (str(minimum), str(maximum), "0", "65535")
    run_gdal(
        "gdal_translate",
        "-of",
        "PNG",
        "-ot",
        "UInt16",
        "-scale",
        *scale,
        str(elevation_tiff),
        str(heightmap),
    )

    metadata = {
        "source": "LINZ Wellington City LiDAR 1 m DEM (2025)",
        "vertical_datum": "NZVD2016",
        "elevation_geotiff": elevation_tiff.name,
        "heightmap": heightmap.name,
        "size_pixels": {"width": width_px, "height": height_px},
        "resolution_metres_per_pixel": width_m / width_px,
        "elevation_metres": {"minimum": minimum, "maximum": maximum},
        "encoding": "uint16 = (elevation - minimum) / (maximum - minimum) * 65535",
    }
    (WORKING / "heightmap.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    if not args.keep_intermediate:
        mosaic.unlink(missing_ok=True)
    print(f"Wrote {heightmap} ({width_px}x{height_px}, {minimum:.2f} to {maximum:.2f} m)")
    print(f"Wrote {elevation_tiff}")


if __name__ == "__main__":
    main()
