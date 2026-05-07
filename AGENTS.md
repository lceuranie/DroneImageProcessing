# AGENTS.md — Drone Mosaic & SfM Pipeline

> Instructions for AI coding agents (Codex / Claude Code / Cursor) working in this
> repository. Human contributors should read this too — it doubles as the project
> playbook.

## 1. Project context

We have a set of nadir (90° down) aerial images captured with a **DJI Neo** consumer
drone over the parking lot of **ISU, Illkirch-Graffenstaden, France**. Source filenames
look like `DJI_YYYYMMDDHHMMSS_NNNN_D.JPG`.

The goal of this repo is a reproducible pipeline that turns the raw image set into:

1. **`metadata.md`** + machine-readable metadata (CSV / JSON) describing every frame.
2. A **georeferenced orthomosaic** of the parking lot (GeoTIFF, EPSG:32632 / WGS84-UTM-32N).
3. A **Structure-from-Motion reconstruction** with a **dense point cloud** (PLY + LAS),
   the "faux LiDAR" deliverable.

The work is staged in three phases of increasing fidelity. Earlier phases must keep
working when later phases are added — they are useful as sanity checks and demos.

| Phase | Deliverable | Tooling |
|---|---|---|
| 1 | Metadata table + per-image GeoTIFFs + naive mosaic | Pure Python (`pyexiftool`, `rasterio`, `pyproj`, `OpenCV`) |
| 2 | True orthomosaic + DSM | OpenDroneMap (Docker) |
| 3 | SfM sparse + MVS dense point cloud | COLMAP (CLI / `pycolmap`) |

## 2. Repository layout

```
drone-mosaic-sfm/
├── AGENTS.md              ← you are here
├── README.md              ← human onboarding
├── requirements.txt       ← Python deps
├── .gitignore
├── data/
│   ├── raw/               ← drop DJI .JPG files here (gitignored)
│   ├── metadata/          ← metadata.md, metadata.csv, metadata.json
│   ├── georeferenced/     ← per-image GeoTIFFs
│   ├── mosaic/            ← orthomosaic outputs
│   └── sfm/               ← COLMAP / ODM project + point clouds
├── src/
│   ├── __init__.py
│   ├── extract_metadata.py
│   ├── georeference.py
│   ├── mosaic.py
│   └── sfm.py
├── scripts/               ← thin CLI wrappers, one per stage
├── notebooks/             ← exploration only, never the source of truth
└── tests/
```

**Rule:** code lives in `src/`. `scripts/` only contains short entry points that parse
args and call into `src/`. Notebooks are for exploration and must not be imported by
production code.

## 3. Coding conventions

- **Python 3.10+**, type hints required on public functions.
- Format with `black`, lint with `ruff`. No commits that fail either.
- `pathlib.Path` for all paths — never raw strings concatenated with `os.path.join`.
- `logging` (not `print`) with module-level loggers: `logger = logging.getLogger(__name__)`.
- Every CLI script accepts `--input` and `--output` as `Path`s and a `--log-level` flag.
- Long-running steps must use `tqdm` progress bars.
- Functions that touch the filesystem must be idempotent: re-running on the same
  inputs/outputs should be a no-op or a clean overwrite, never a half-broken state.
- Pin coordinate systems explicitly using EPSG codes. Default working CRS:
  **EPSG:32632** (UTM 32N). Default geographic CRS: **EPSG:4326** (WGS84).

## 4. External dependencies (install before running)

These are not pip-installable and must be present on the system:

- **ExifTool** ≥ 12.x — `apt install libimage-exiftool-perl` or `brew install exiftool`.
  Required by `pyexiftool` for DJI XMP fields.
- **COLMAP** ≥ 3.8 — `apt install colmap` (CPU build) or build from source for CUDA.
  Required for Phase 3.
- **Docker** — required to run **OpenDroneMap** in Phase 2 (`opendronemap/odm` image).
- **GDAL** ≥ 3.4 — usually pulled in transitively by `rasterio`, but the CLI tools
  (`gdalwarp`, `gdal_translate`) are useful for debugging.

The agent should detect missing dependencies at script startup and emit a clear error
naming the missing tool and the install command — never fail with a cryptic
`FileNotFoundError`.

## 5. Pipeline stages (the contract)

### Stage 1 — Metadata extraction (`src/extract_metadata.py`)

**Input:** directory of DJI `.JPG` files.
**Output:**
- `data/metadata/metadata.json` — full record per image, the source of truth.
- `data/metadata/metadata.csv` — flat table for quick inspection.
- `data/metadata/metadata.md` — human-readable Markdown summary (one row per image
  + dataset-level stats: bounding box, altitude range, capture time span, mean GSD).

**Required fields per image** (must extract all of these):

| Field | Source tag(s) |
|---|---|
| `filename` | — |
| `datetime_utc` | `EXIF:DateTimeOriginal` + `EXIF:OffsetTimeOriginal` |
| `latitude`, `longitude` | `EXIF:GPSLatitude` + ref, `EXIF:GPSLongitude` + ref |
| `absolute_altitude_m` | `XMP:AbsoluteAltitude` (DJI) |
| `relative_altitude_m` | `XMP:RelativeAltitude` (DJI) — height above takeoff |
| `gimbal_yaw_deg`, `gimbal_pitch_deg`, `gimbal_roll_deg` | `XMP:GimbalYawDegree`, etc. |
| `flight_yaw_deg`, `flight_pitch_deg`, `flight_roll_deg` | `XMP:FlightYawDegree`, etc. |
| `image_width`, `image_height` | `EXIF:ImageWidth`, `EXIF:ImageHeight` |
| `focal_length_mm` | `EXIF:FocalLength` |
| `focal_length_35mm_equiv` | `EXIF:FocalLengthIn35mmFormat` |
| `camera_model` | `EXIF:Model` |
| `iso`, `shutter`, `f_number` | standard EXIF |

**Implementation hints:**
- Use `pyexiftool.ExifToolHelper` in a `with` block — one process for the whole batch
  is ~100× faster than spawning per file.
- DJI XMP fields appear under the `XMP-drone-dji:` group in ExifTool output. Ask for
  `-G` (group names) so you can disambiguate from generic XMP.
- Sanity check: every image must have GPS. If `latitude` is missing, log a warning
  and exclude the image from downstream stages.

### Stage 2 — Per-image georeferencing (`src/georeference.py`)

**Input:** `metadata.json` + raw images.
**Output:** one GeoTIFF per image in `data/georeferenced/`, plus a single
`footprints.geojson` with all image footprints as polygons.

**Method (single-image projection, nadir assumption):**
1. Compute **GSD** (ground sampling distance, m/pixel):
   `GSD = (sensor_width_mm × relative_altitude_m) / (focal_length_mm × image_width_px)`
   For DJI Neo, sensor width ≈ **6.4 mm** (1/2" sensor) — confirm from EXIF
   `FocalPlaneXResolution` if available, otherwise hardcode with a constant in
   `src/constants.py` and document the source.
2. Footprint dimensions: `width_m = GSD × image_width_px`, same for height.
3. Convert image center (lat, lon) to UTM (EPSG:32632) with `pyproj.Transformer`.
4. Build the affine transform with `rasterio.transform.from_origin`, applying
   gimbal yaw as a rotation. For nadir flights with gimbal pitch ≈ -90°, the yaw
   rotation is the only one that matters.
5. Write GeoTIFF with `rasterio.open(..., "w", driver="GTiff", crs="EPSG:32632",
   transform=...)`.

**Note:** this is a *first-order* approximation — it ignores terrain relief, lens
distortion, and non-nadir tilt. Phase 2 (ODM) is what you trust for measurements.
Phase 1 is for visualization, sanity-checking GPS, and teaching the geometry.

### Stage 3 — Naive mosaic (`src/mosaic.py`)

**Input:** GeoTIFFs from Stage 2.
**Output:** `data/mosaic/mosaic_naive.tif`.

Use `rasterio.merge.merge()` with `method="last"` or a custom feathering callable.
This will show seams and parallax artifacts — that's expected and motivates Phase 2.

Also produce `data/mosaic/preview.png` (downsampled, for the README) and
`data/mosaic/coverage.geojson` (union of footprints, for QGIS inspection).

### Stage 4 — Orthomosaic via OpenDroneMap (`scripts/run_odm.sh`)

Wrap the official Docker image:

```bash
docker run -ti --rm -v "$(pwd)/data:/datasets" \
  opendronemap/odm --project-path /datasets sfm \
  --orthophoto-resolution 2 \
  --dsm \
  --pc-las \
  --feature-quality high
```

(Expects images in `data/sfm/images/` per ODM convention.)

Outputs of interest:
- `data/sfm/odm_orthophoto/odm_orthophoto.tif` → copy to `data/mosaic/mosaic_odm.tif`
- `data/sfm/odm_dem/dsm.tif`
- `data/sfm/odm_georeferenced_model/odm_georeferenced_model.laz` → point cloud

### Stage 5 — SfM + dense point cloud via COLMAP (`src/sfm.py`)

Programmatic pipeline using `pycolmap`:

1. `pycolmap.extract_features(database, image_dir)` — SIFT.
2. `pycolmap.match_exhaustive(database)` (small dataset) or
   `match_sequential` (large, ordered flight).
3. `pycolmap.incremental_mapping(database, image_dir, sparse_dir)` → sparse model.
4. Convert sparse model + images to dense MVS workspace
   (`pycolmap.undistort_images`).
5. Run **PatchMatch stereo** + **stereo fusion** (CLI fallback if pycolmap lacks
   bindings on the target platform):
   ```bash
   colmap patch_match_stereo --workspace_path data/sfm/dense
   colmap stereo_fusion --workspace_path data/sfm/dense \
       --output_path data/sfm/dense/fused.ply
   ```
6. Export to LAS for GIS interoperability with `laspy`:
   read PLY with `open3d`, dump XYZ + RGB to a LAS 1.4 file with the project CRS.
7. Georegister the COLMAP model: write a text file mapping each image filename
   to its GPS-derived UTM XYZ, then run `colmap model_aligner` with `--ref_is_gps 1`.

**Acceptance criterion:** the fused PLY opens cleanly in CloudCompare and aligns
within ~1 m of the ODM orthomosaic when displayed together.

## 6. How agents should work

- **Read this file in full before editing.** If a change contradicts AGENTS.md,
  update AGENTS.md in the same commit and explain why in the message.
- **One stage at a time.** Don't refactor Stage 3 while implementing Stage 5.
- **Tests before features for anything math-heavy.** GSD computation, coordinate
  transforms, and affine construction must have unit tests in `tests/` with at
  least one synthetic case where the answer is hand-computable.
- **Never commit `data/raw/` contents.** Drone images are large and may be
  subject to privacy review (the sample image contains people).
- **When in doubt about a DJI tag name**, run `exiftool -G -a -s sample.JPG` on
  one of the images in `data/raw/` and grep the output. Don't guess.
- **Document every magic constant** (sensor width, default altitude, EPSG code)
  in `src/constants.py` with a comment naming the source.

## 7. Privacy & safety

The sample frame shows identifiable people. Before publishing any orthomosaic or
point cloud:
- Run a face-blurring pass on raw images, or
- Crop the mosaic to the parking surface only.

`src/anonymize.py` is a placeholder for a future YOLO-based blur step. Do not skip
this if outputs leave the local machine.

## 8. References (read these, don't re-derive)

- DJI XMP metadata reference: <https://exiftool.org/TagNames/DJI.html>
- Rasterio georeferencing cookbook: <https://rasterio.readthedocs.io/en/latest/topics/georeferencing.html>
- OpenDroneMap docs: <https://docs.opendronemap.org/>
- COLMAP tutorial: <https://colmap.github.io/tutorial.html>
- pycolmap examples: <https://github.com/colmap/pycolmap>
- DJI Neo specs (for sensor size / focal length sanity check): DJI official site,
  cross-check against EXIF on your own images — manufacturer specs and EXIF
  occasionally disagree.
