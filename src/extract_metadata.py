"""Stage 1 — metadata extraction.

Reads every DJI .JPG in --input and writes:
    <output>/metadata.json   — full record per image (source of truth)
    <output>/metadata.csv    — flat table
    <output>/metadata.md     — human-readable summary

Requires the exiftool binary on PATH (system dep).

Usage:
    python -m src.extract_metadata --input data/raw --output data/metadata
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from tqdm import tqdm

try:
    import exiftool  # provided by PyExifTool
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "PyExifTool is not installed. Run: pip install -r requirements.txt"
    ) from exc

logger = logging.getLogger(__name__)


# Mapping of (canonical name) -> tuple of ExifTool tag aliases to try in order.
# Group prefix ('EXIF', 'XMP', 'Composite') is included so we know exactly what
# we're reading; the actual key in pyexiftool output uses ':' separators.
TAG_MAP: dict[str, tuple[str, ...]] = {
    "datetime_original":    ("EXIF:DateTimeOriginal", "Composite:SubSecDateTimeOriginal"),
    "latitude":             ("Composite:GPSLatitude", "EXIF:GPSLatitude"),
    "longitude":            ("Composite:GPSLongitude", "EXIF:GPSLongitude"),
    "absolute_altitude_m":  ("XMP:AbsoluteAltitude",),
    "relative_altitude_m":  ("XMP:RelativeAltitude",),
    "gimbal_yaw_deg":       ("XMP:GimbalYawDegree",),
    "gimbal_pitch_deg":     ("XMP:GimbalPitchDegree",),
    "gimbal_roll_deg":      ("XMP:GimbalRollDegree",),
    "flight_yaw_deg":       ("XMP:FlightYawDegree",),
    "flight_pitch_deg":     ("XMP:FlightPitchDegree",),
    "flight_roll_deg":      ("XMP:FlightRollDegree",),
    "image_width":          ("EXIF:ImageWidth", "File:ImageWidth"),
    "image_height":         ("EXIF:ImageHeight", "File:ImageHeight"),
    "focal_length_mm":      ("EXIF:FocalLength",),
    "focal_length_35mm":    ("EXIF:FocalLengthIn35mmFormat",),
    "camera_model":         ("EXIF:Model",),
    "iso":                  ("EXIF:ISO",),
    "shutter":              ("EXIF:ExposureTime",),
    "f_number":             ("EXIF:FNumber",),
}


@dataclass
class ImageRecord:
    filename: str
    datetime_original: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    absolute_altitude_m: float | None = None
    relative_altitude_m: float | None = None
    gimbal_yaw_deg: float | None = None
    gimbal_pitch_deg: float | None = None
    gimbal_roll_deg: float | None = None
    flight_yaw_deg: float | None = None
    flight_pitch_deg: float | None = None
    flight_roll_deg: float | None = None
    image_width: int | None = None
    image_height: int | None = None
    focal_length_mm: float | None = None
    focal_length_35mm: float | None = None
    camera_model: str | None = None
    iso: int | None = None
    shutter: float | None = None
    f_number: float | None = None


def _coerce(value: Any) -> Any:
    """ExifTool sometimes returns numerics as str ('+45.2'); normalize."""
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip().lstrip("+")
        try:
            return float(s) if "." in s or "e" in s.lower() else int(s)
        except ValueError:
            return value
    return value


def _first_present(metadata: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        if alias in metadata:
            return _coerce(metadata[alias])
    return None


def extract_one(metadata: dict[str, Any], path: Path) -> ImageRecord:
    record = ImageRecord(filename=path.name)
    for field, aliases in TAG_MAP.items():
        setattr(record, field, _first_present(metadata, aliases))
    return record


def check_exiftool() -> None:
    if shutil.which("exiftool") is None:
        raise SystemExit(
            "ExifTool binary not found on PATH. Install it:\n"
            "  Debian/Ubuntu: sudo apt install libimage-exiftool-perl\n"
            "  macOS:         brew install exiftool"
        )


def extract_all(input_dir: Path) -> list[ImageRecord]:
    images = sorted(p for p in input_dir.iterdir()
                    if p.suffix.lower() in {".jpg", ".jpeg"})
    if not images:
        raise SystemExit(f"No .JPG files found in {input_dir}")

    logger.info("Found %d images in %s", len(images), input_dir)

    records: list[ImageRecord] = []
    # One ExifTool process for the whole batch — orders of magnitude faster.
    with exiftool.ExifToolHelper() as et:
        for path in tqdm(images, desc="Reading EXIF/XMP"):
            try:
                meta = et.get_metadata(str(path))[0]
                records.append(extract_one(meta, path))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed on %s: %s", path.name, exc)

    missing_gps = [r.filename for r in records if r.latitude is None]
    if missing_gps:
        logger.warning("%d images missing GPS — they will be skipped downstream: %s",
                       len(missing_gps), missing_gps[:5])
    return records


def write_outputs(records: list[ImageRecord], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [asdict(r) for r in records]

    # JSON — source of truth
    (output_dir / "metadata.json").write_text(
        json.dumps(rows, indent=2, default=str), encoding="utf-8"
    )

    # CSV — for quick inspection
    df = pd.DataFrame(rows)
    df.to_csv(output_dir / "metadata.csv", index=False)

    # Markdown summary
    md = _render_markdown(df)
    (output_dir / "metadata.md").write_text(md, encoding="utf-8")
    logger.info("Wrote metadata.{json,csv,md} to %s", output_dir)


def _render_markdown(df: pd.DataFrame) -> str:
    lines: list[str] = ["# Drone image metadata\n"]
    lines.append(f"**Total images:** {len(df)}\n")

    if "latitude" in df and df["latitude"].notna().any():
        lines.append("## Spatial extent (WGS84)\n")
        lines.append(f"- Latitude:  {df['latitude'].min():.6f} → {df['latitude'].max():.6f}")
        lines.append(f"- Longitude: {df['longitude'].min():.6f} → {df['longitude'].max():.6f}")
        if "relative_altitude_m" in df and df["relative_altitude_m"].notna().any():
            lines.append(f"- Relative altitude (m): "
                         f"{df['relative_altitude_m'].min():.1f} → "
                         f"{df['relative_altitude_m'].max():.1f}")
        lines.append("")

    if "datetime_original" in df and df["datetime_original"].notna().any():
        lines.append("## Capture window\n")
        lines.append(f"- First: `{df['datetime_original'].min()}`")
        lines.append(f"- Last:  `{df['datetime_original'].max()}`\n")

    lines.append("## Per-image\n")
    show_cols = [
        "filename", "datetime_original", "latitude", "longitude",
        "relative_altitude_m", "gimbal_yaw_deg", "focal_length_mm",
    ]
    cols = [c for c in show_cols if c in df.columns]
    lines.append(df[cols].to_markdown(index=False, floatfmt=".4f"))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input",  type=Path, required=True, help="Folder of DJI .JPG")
    parser.add_argument("--output", type=Path, required=True, help="Output dir for metadata")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    check_exiftool()

    if not args.input.is_dir():
        raise SystemExit(f"Input directory not found: {args.input}")

    records = extract_all(args.input)
    write_outputs(records, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
