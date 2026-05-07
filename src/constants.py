"""Project-wide constants. Every value here is documented with its source."""

from __future__ import annotations

# Coordinate reference systems
CRS_GEOGRAPHIC = "EPSG:4326"   # WGS84 lat/lon — what GPS records
CRS_WORKING = "EPSG:32632"     # UTM zone 32N — covers Strasbourg / Illkirch.
                               # All metric computations (GSD, footprints,
                               # mosaic transforms) happen in this CRS.

# DJI Neo camera intrinsics
# Source: EXIF read on real images from this dataset (camera model FC8671).
# Verify on your own batch with:
#   exiftool -G -a -s data/raw/DJI_*.JPG | grep -iE "focal|sensor|model"
DJI_NEO_CAMERA_MODEL = "FC8671"
DJI_NEO_FOCAL_LENGTH_MM = 2.598          # native, from EXIF:FocalLength
DJI_NEO_FOCAL_LENGTH_35MM = 14           # from EXIF:FocalLengthIn35mmFormat
DJI_NEO_IMAGE_WIDTH_PX = 4000            # 16:9 still mode used by this dataset
DJI_NEO_IMAGE_HEIGHT_PX = 2256
# Sensor width derived from focal-length crop factor:
#   crop = 35mm_equiv / native = 14 / 2.598 ≈ 5.39
#   sensor_width_mm ≈ 36 / 5.39 ≈ 6.68
# Confirm by extracting a calibrated value from ODM/COLMAP after Stage 4 or 5.
DJI_NEO_SENSOR_WIDTH_MM = 6.68
DJI_NEO_SENSOR_HEIGHT_MM = 3.76          # scaled from width by 16:9

# Pipeline defaults
DEFAULT_MOSAIC_RESOLUTION_M = 0.02   # 2 cm/pixel — adjust to drone altitude
DEFAULT_FEATURE_QUALITY = "high"     # ODM feature-extraction quality
