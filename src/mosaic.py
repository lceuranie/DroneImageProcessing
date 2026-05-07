"""Stage 3 - naive mosaic from georeferenced GeoTIFFs.

Merges the per-image GeoTIFFs produced by Stage 2 into a single mosaic GeoTIFF
and writes a downsampled PNG preview for quick inspection.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from rasterio.merge import merge
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.warp import calculate_default_transform
from rasterio.enums import Resampling

logger = logging.getLogger(__name__)

PREVIEW_MAX_WIDTH_PX = 2000


def list_input_geotiffs(input_dir: Path) -> list[Path]:
    """Return all Stage 2 GeoTIFFs in a stable order."""
    geotiffs = sorted(
        path for path in input_dir.glob("*.tif") if path.is_file()
    )
    if not geotiffs:
        raise SystemExit(f"No GeoTIFFs found in {input_dir}")
    return geotiffs


def build_mosaic(input_dir: Path) -> tuple[np.ndarray, rasterio.Affine, dict[str, object]]:
    """Merge all input GeoTIFFs into a single mosaic array."""
    geotiff_paths = list_input_geotiffs(input_dir)
    logger.info("Merging %d GeoTIFFs from %s", len(geotiff_paths), input_dir)

    datasets = [rasterio.open(path) for path in geotiff_paths]
    vrts: list[WarpedVRT] = []
    try:
        for dataset in datasets:
            resolution_x = float(np.hypot(dataset.transform.a, dataset.transform.b))
            resolution_y = float(np.hypot(dataset.transform.d, dataset.transform.e))
            resolution = (resolution_x + resolution_y) / 2.0
            transform, width, height = calculate_default_transform(
                dataset.crs,
                dataset.crs,
                dataset.width,
                dataset.height,
                *dataset.bounds,
                resolution=resolution,
            )
            vrts.append(
                WarpedVRT(
                    dataset,
                    crs=dataset.crs,
                    transform=transform,
                    width=width,
                    height=height,
                    resampling=Resampling.nearest,
                )
            )

        mosaic_array, mosaic_transform = merge(vrts, method="last")
        profile = datasets[0].profile.copy()
    finally:
        for vrt in vrts:
            vrt.close()
        for dataset in datasets:
            dataset.close()

    profile.update(
        driver="GTiff",
        height=int(mosaic_array.shape[1]),
        width=int(mosaic_array.shape[2]),
        count=int(mosaic_array.shape[0]),
        transform=mosaic_transform,
    )
    profile.pop("blockxsize", None)
    profile.pop("blockysize", None)
    profile.pop("tiled", None)
    return mosaic_array, mosaic_transform, profile


def write_mosaic(output_path: Path, mosaic_array: np.ndarray, profile: dict[str, object]) -> None:
    """Write the merged mosaic to GeoTIFF."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_path, "w", **profile) as dataset:
        dataset.write(mosaic_array)
    logger.info("Wrote mosaic GeoTIFF to %s", output_path)


def write_preview_png(mosaic_array: np.ndarray, preview_path: Path) -> None:
    """Write a downsampled RGB preview PNG."""
    rgb = np.moveaxis(mosaic_array[:3], 0, 2)
    image = Image.fromarray(rgb)
    if image.width > PREVIEW_MAX_WIDTH_PX:
        new_height = max(1, round(image.height * (PREVIEW_MAX_WIDTH_PX / image.width)))
        image = image.resize((PREVIEW_MAX_WIDTH_PX, new_height), Image.Resampling.LANCZOS)

    preview_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(preview_path)
    logger.info("Wrote preview PNG to %s", preview_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Folder of per-image GeoTIFFs from Stage 2",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output mosaic GeoTIFF path",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.input.is_dir():
        raise SystemExit(f"Input directory not found: {args.input}")

    mosaic_array, _mosaic_transform, profile = build_mosaic(args.input)
    write_mosaic(args.output, mosaic_array, profile)
    write_preview_png(mosaic_array, args.output.parent / "preview.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
