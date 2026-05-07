"""Stage 6 - RGB vegetation indices from the ODM orthomosaic."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import matplotlib
import numpy as np
from PIL import Image
import rasterio

logger = logging.getLogger(__name__)

PREVIEW_MAX_LONG_SIDE_PX = 2000
DISPLAY_VMIN = -0.3
DISPLAY_VMAX = 0.3
INDEX_SPECS = {
    "vari": ("VARI", lambda r, g, b: ((g - r), (g + r - b))),
    "gli": ("GLI", lambda r, g, b: ((2.0 * g - r - b), (2.0 * g + r + b))),
    "ngrdi": ("NGRDI", lambda r, g, b: ((g - r), (g + r))),
}


def compute_index(
    numerator: np.ndarray,
    denominator: np.ndarray,
    valid_mask: np.ndarray,
) -> np.ndarray:
    """Compute a clipped float32 vegetation index with NaN nodata."""
    output = np.full(numerator.shape, np.nan, dtype=np.float32)
    index_valid = valid_mask & (denominator != 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        values = numerator[index_valid] / denominator[index_valid]
    output[index_valid] = np.clip(values, -1.0, 1.0).astype(np.float32)
    return output


def build_preview_rgba(index_array: np.ndarray) -> Image.Image:
    """Create an RGBA preview image with transparent nodata."""
    cmap = matplotlib.colormaps["RdYlGn"]
    normalized = np.clip(
        (index_array - DISPLAY_VMIN) / (DISPLAY_VMAX - DISPLAY_VMIN),
        0.0,
        1.0,
    )
    rgba = cmap(normalized, bytes=True)
    rgba = np.asarray(rgba, dtype=np.uint8).copy()
    rgba[np.isnan(index_array), 3] = 0

    image = Image.fromarray(rgba, mode="RGBA")
    long_side = max(image.size)
    scale = min(1.0, PREVIEW_MAX_LONG_SIDE_PX / long_side)
    new_size = (
        max(1, round(image.width * scale)),
        max(1, round(image.height * scale)),
    )
    if new_size != image.size:
        image = image.resize(new_size, Image.Resampling.LANCZOS)
    return image


def write_index_geotiff(
    output_path: Path,
    index_array: np.ndarray,
    profile: dict[str, object],
) -> None:
    """Write a single-band float32 GeoTIFF."""
    output_profile = profile.copy()
    output_profile.update(
        driver="GTiff",
        count=1,
        dtype="float32",
        nodata=np.nan,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_path, "w", **output_profile) as dst:
        dst.write(index_array, 1)


def write_preview_png(output_path: Path, image: Image.Image) -> None:
    """Write the preview PNG."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def run(input_path: Path, output_dir: Path) -> dict[str, np.ndarray]:
    """Compute all requested vegetation indices and previews."""
    with rasterio.open(input_path) as src:
        if src.count < 3:
            raise SystemExit(f"Expected at least 3 bands in {input_path}")

        rgb = src.read([1, 2, 3]).astype(np.float32)
        valid_mask = src.dataset_mask() > 0
        profile = src.profile.copy()

    red = rgb[0]
    green = rgb[1]
    blue = rgb[2]

    indices: dict[str, np.ndarray] = {}
    for slug, (_label, formula) in INDEX_SPECS.items():
        numerator, denominator = formula(red, green, blue)
        index_array = compute_index(numerator, denominator, valid_mask)
        indices[slug] = index_array

        geotiff_path = output_dir / f"{slug}.tif"
        preview_path = output_dir / f"{slug}_preview.png"
        write_index_geotiff(geotiff_path, index_array, profile)
        write_preview_png(preview_path, build_preview_rgba(index_array))
        logger.info("Wrote %s and %s", geotiff_path, preview_path)

    return indices


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.input.is_file():
        raise SystemExit(f"Input orthomosaic not found: {args.input}")

    run(args.input, args.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
