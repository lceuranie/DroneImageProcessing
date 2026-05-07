"""Stage 2 - per-image georeferencing.

Reads metadata.json, projects each image to a GeoTIFF in EPSG:32632, and writes
a GeoJSON of all footprints.

Usage:
    python -m src.georeference \
        --metadata data/metadata/metadata.json \
        --images data/raw \
        --output data/georeferenced
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np
from tqdm import tqdm

from .constants import (
    CRS_GEOGRAPHIC,
    CRS_WORKING,
    DJI_NEO_FOCAL_LENGTH_MM,
    DJI_NEO_IMAGE_HEIGHT_PX,
    DJI_NEO_IMAGE_WIDTH_PX,
    DJI_NEO_SENSOR_WIDTH_MM,
)

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Pillow is not installed. Run: pip install -r requirements.txt"
    ) from exc

try:
    import rasterio
    from affine import Affine
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "rasterio is not installed. Run: pip install -r requirements.txt"
    ) from exc

try:
    from pyproj import Transformer
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "pyproj is not installed. Run: pip install -r requirements.txt"
    ) from exc

logger = logging.getLogger(__name__)


def compute_gsd(
    sensor_width_mm: float,
    relative_altitude_m: float,
    focal_length_mm: float,
    image_width_px: int,
) -> float:
    """Compute ground sampling distance in meters per pixel."""
    if sensor_width_mm <= 0:
        raise ValueError("sensor_width_mm must be positive")
    if relative_altitude_m <= 0:
        raise ValueError("relative_altitude_m must be positive")
    if focal_length_mm <= 0:
        raise ValueError("focal_length_mm must be positive")
    if image_width_px <= 0:
        raise ValueError("image_width_px must be positive")

    return (sensor_width_mm * relative_altitude_m) / (
        focal_length_mm * image_width_px
    )


def build_transform(
    center_x: float,
    center_y: float,
    gsd_m_per_pixel: float,
    width_px: int,
    height_px: int,
    yaw_deg: float,
) -> Affine:
    """Build a pixel-to-world transform centered on the image center."""
    return (
        Affine.translation(center_x, center_y)
        * Affine.rotation(-yaw_deg)
        * Affine.scale(gsd_m_per_pixel, -gsd_m_per_pixel)
        * Affine.translation(-width_px / 2.0, -height_px / 2.0)
    )


def load_metadata(metadata_path: Path) -> list[dict[str, Any]]:
    """Load Stage 1 metadata records."""
    with metadata_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, list):
        raise SystemExit(f"Metadata file must contain a list of records: {metadata_path}")
    return data


def build_footprint_feature(
    filename: str,
    transform: Affine,
    width_px: int,
    height_px: int,
    gsd_m_per_pixel: float,
) -> dict[str, Any]:
    """Convert an image transform into a GeoJSON polygon feature."""
    corners_px = [
        (0.0, 0.0),
        (float(width_px), 0.0),
        (float(width_px), float(height_px)),
        (0.0, float(height_px)),
        (0.0, 0.0),
    ]
    coordinates = [[list(transform * corner) for corner in corners_px]]
    return {
        "type": "Feature",
        "properties": {
            "filename": filename,
            "gsd_m_per_pixel": gsd_m_per_pixel,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": coordinates,
        },
    }


def write_geotiff(
    image_path: Path,
    output_path: Path,
    transform: Affine,
    width_px: int,
    height_px: int,
) -> None:
    """Write a georeferenced GeoTIFF for one input image."""
    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        array = np.asarray(rgb)

    if array.shape[1] != width_px or array.shape[0] != height_px:
        logger.warning(
            "Image dimensions for %s differ from metadata (%s x %s actual, %s x %s metadata); using actual image size.",
            image_path.name,
            array.shape[1],
            array.shape[0],
            width_px,
            height_px,
        )
        width_px = int(array.shape[1])
        height_px = int(array.shape[0])

    bands = np.moveaxis(array, 2, 0)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        width=width_px,
        height=height_px,
        count=3,
        dtype=bands.dtype,
        crs=CRS_WORKING,
        transform=transform,
    ) as dataset:
        dataset.write(bands)


def georeference_images(
    metadata_path: Path,
    images_dir: Path,
    output_dir: Path,
) -> tuple[int, list[float]]:
    """Georeference every metadata-backed image with valid GPS."""
    output_dir.mkdir(parents=True, exist_ok=True)
    transformer = Transformer.from_crs(
        CRS_GEOGRAPHIC,
        CRS_WORKING,
        always_xy=True,
    )

    records = load_metadata(metadata_path)
    footprint_features: list[dict[str, Any]] = []
    gsds: list[float] = []
    geotiff_count = 0

    for record in tqdm(records, desc="Georeferencing images"):
        filename = record.get("filename")
        if not filename:
            logger.warning("Skipping metadata record without filename: %s", record)
            continue

        latitude = record.get("latitude")
        longitude = record.get("longitude")
        if latitude is None or longitude is None:
            logger.warning("Skipping %s because GPS is missing.", filename)
            continue

        relative_altitude_m = float(
            record.get("relative_altitude_m") or 0.0
        )
        if relative_altitude_m <= 0:
            logger.warning("Skipping %s because relative altitude is invalid.", filename)
            continue

        focal_length_mm = float(
            record.get("focal_length_mm") or DJI_NEO_FOCAL_LENGTH_MM
        )
        image_width = int(record.get("image_width") or DJI_NEO_IMAGE_WIDTH_PX)
        image_height = int(record.get("image_height") or DJI_NEO_IMAGE_HEIGHT_PX)
        yaw_deg = float(record.get("gimbal_yaw_deg") or 0.0)

        image_path = images_dir / filename
        if not image_path.is_file():
            logger.warning("Skipping %s because the source image is missing.", filename)
            continue

        gsd_m_per_pixel = compute_gsd(
            sensor_width_mm=DJI_NEO_SENSOR_WIDTH_MM,
            relative_altitude_m=relative_altitude_m,
            focal_length_mm=focal_length_mm,
            image_width_px=image_width,
        )
        center_x, center_y = transformer.transform(float(longitude), float(latitude))
        transform = build_transform(
            center_x=center_x,
            center_y=center_y,
            gsd_m_per_pixel=gsd_m_per_pixel,
            width_px=image_width,
            height_px=image_height,
            yaw_deg=yaw_deg,
        )

        output_path = output_dir / f"{Path(filename).stem}.tif"
        write_geotiff(
            image_path=image_path,
            output_path=output_path,
            transform=transform,
            width_px=image_width,
            height_px=image_height,
        )
        footprint_features.append(
            build_footprint_feature(
                filename=filename,
                transform=transform,
                width_px=image_width,
                height_px=image_height,
                gsd_m_per_pixel=gsd_m_per_pixel,
            )
        )
        gsds.append(gsd_m_per_pixel)
        geotiff_count += 1

    footprints = {
        "type": "FeatureCollection",
        "features": footprint_features,
    }
    (output_dir / "footprints.geojson").write_text(
        json.dumps(footprints, indent=2),
        encoding="utf-8",
    )
    logger.info("Wrote %d GeoTIFFs to %s", geotiff_count, output_dir)
    logger.info("Wrote footprints.geojson with %d features", len(footprint_features))
    return geotiff_count, gsds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.metadata.is_file():
        raise SystemExit(f"Metadata file not found: {args.metadata}")
    if not args.images.is_dir():
        raise SystemExit(f"Images directory not found: {args.images}")

    georeference_images(args.metadata, args.images, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
