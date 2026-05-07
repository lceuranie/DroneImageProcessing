# Drone Mosaic & SfM Pipeline

Aerial photogrammetry workshop pipeline for processing **DJI Neo** nadir imagery
captured over the parking lot of **ISU, Illkirch-Graffenstaden** (France, UTM 32N).

From a folder of `DJI_*.JPG` files we produce:

1. **Image metadata** — `metadata.md` / `.csv` / `.json` with GPS, altitude, gimbal
   attitude, camera intrinsics for every frame.
2. **Orthomosaic** — a single georeferenced GeoTIFF of the parking lot.
3. **Structure-from-Motion point cloud** — dense 3D reconstruction (PLY + LAS),
   the "faux LiDAR" deliverable.

## Pipeline at a glance

```
   data/raw/*.JPG
        │
        ▼
   ┌──────────────────────┐
   │ 1. extract_metadata  │ → data/metadata/metadata.{json,csv,md}
   └──────────────────────┘
        │
        ▼
   ┌──────────────────────┐
   │ 2. georeference      │ → data/georeferenced/*.tif + footprints.geojson
   └──────────────────────┘
        │
        ├──────────────► naive mosaic ──► data/mosaic/mosaic_naive.tif
        │
        ▼
   ┌──────────────────────┐
   │ 3. OpenDroneMap      │ → data/mosaic/mosaic_odm.tif + DSM
   └──────────────────────┘
        │
        ▼
   ┌──────────────────────┐
   │ 4. COLMAP SfM + MVS  │ → data/sfm/dense/fused.{ply,las}
   └──────────────────────┘
```

## Quick start

```bash
# 1. system deps (Ubuntu/Debian)
sudo apt install libimage-exiftool-perl colmap gdal-bin

# 2. python env
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. drop your DJI .JPG files into data/raw/

# 4. run stage 1
python -m src.extract_metadata --input data/raw --output data/metadata
```

## Interactive viewer

Build the interactive folium viewer with:

```bash
python -m src.viewer
```

This writes:

- `data/visualization/viewer.html`

On Windows you can also launch it with:

- `scripts\run_viewer.bat`

Viewer controls:

- Use the top-right layer control to toggle RGB, VARI, GLI, NGRDI, and footprints.
- Use the bottom-right panel to change each overlay's opacity independently.
- Click `Adjust position` to enter drag mode for visible overlays and align them manually against the basemap.
- Click `Reset` to snap overlays back to their original georeferenced positions.
- Click `Copy offset` to copy the currently selected overlay's `dx_m` / `dy_m` correction as JSON.

## Project layout

See **[AGENTS.md](AGENTS.md)** for the full specification — pipeline stages,
deliverable contracts, coding conventions, and AI-agent working rules.

## Context

- **Drone:** DJI Neo (consumer, no RTK). GPS accuracy ~1–3 m horizontal.
- **Imagery:** 90° down (nadir), expected ~70–80% overlap for SfM.
- **Working CRS:** EPSG:32632 (UTM zone 32N).
- **Geographic CRS:** EPSG:4326 (WGS84).

## License

Workshop / educational use. Raw imagery contains identifiable people — see the
"Privacy & safety" section in `AGENTS.md` before publishing any output.
