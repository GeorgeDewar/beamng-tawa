# beamng-tawa

This is a project to create a BeamNG map of Tawa.

A guiding principle is to automate as much as possible, so I'll be using a fork of MapNG, and ideally feeding any improvements back to MapNG.

## Building

Ensure that GeorgeDewar/mapng is cloned in a neighbouring directory "mapng".

Run `./build.sh`.

## Elevation heightmap

`build_heightmap.py` reads `config.yaml`, downloads only the LINZ Wellington
City DEM GeoTIFFs that overlap the configured area, and uses GDAL to create:

- `working/elevation.tiff`: a single EPSG:2193 GeoTIFF cropped and resampled to
	the requested area.
- `working/heightmap.png`: a 16-bit grayscale PNG with dimensions
	`area.size / heightmap.resolution`.
- `working/heightmap.json`: elevation range and heightmap encoding metadata.

GDAL command-line utilities (`gdalbuildvrt`, `gdalwarp`, `gdalinfo`, and
`gdal_translate`) must be available on `PATH`. Run the builder with:

`python build_heightmap.py`
