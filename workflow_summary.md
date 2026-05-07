# Workflow Summary

This file is a concise recap of the work completed in this repository during the current buildout session, so the workflow can be recovered later without relying on chat history.

## Scope Completed

The project was taken from a scaffold/spec state to a working end-to-end prototype for:

- Stage 1: metadata extraction
- Stage 2: per-image georeferencing
- Stage 3: naive mosaic generation
- Stage 4: OpenDroneMap execution wrapper and output handling
- Stage 6: RGB vegetation index generation
- Interactive folium-based web viewer

## Stage 1

Executed:

- `python -m src.extract_metadata --input data/raw --output data/metadata`

Result:

- Metadata extraction succeeded after installing missing local dependencies and ExifTool.
- Outputs were written to:
  - `data/metadata/metadata.json`
  - `data/metadata/metadata.csv`
  - `data/metadata/metadata.md`

Observed dataset summary:

- Total images: 47
- Latitude range: 48.522170 to 48.522602
- Longitude range: 7.736734 to 7.736894
- Relative altitude range: 17.3 m to 18.1 m
- Missing GPS images: 0

## Stage 2

Implemented:

- `src/georeference.py`
- `tests/test_georeference.py`

What it does:

- Reads `metadata.json`
- Computes GSD using constants from `src/constants.py`
- Projects images into `EPSG:32632`
- Writes one GeoTIFF per image
- Writes `footprints.geojson`

Executed:

- `python -m src.georeference --metadata data/metadata/metadata.json --images data/raw --output data/georeferenced`

Result:

- 47 GeoTIFFs produced
- `data/georeferenced/footprints.geojson` produced
- Mean GSD: about 1.148 cm/pixel

## Footprint Verification

Created:

- `notebooks/01_check_footprints.ipynb`
- `data/metadata/footprints_map.html`

Purpose:

- Load footprints
- Display them in folium
- Save an interactive footprint map

Interpretation:

- The flight coverage appeared contiguous, without major gaps or obvious outliers.

## Stage 3

Implemented:

- `src/mosaic.py`

What it does:

- Merges Stage 2 GeoTIFFs using `rasterio.merge.merge()`
- Handles rotated inputs by normalizing through VRTs
- Writes:
  - `data/mosaic/mosaic_naive.tif`
  - `data/mosaic/preview.png`

Executed:

- `python -m src.mosaic --input data/georeferenced --output data/mosaic/mosaic_naive.tif`

Result:

- Naive mosaic size: 5708 x 7993 px
- File size: about 130.6 MB
- Visual result: recognizable parking lot, but with obvious seams and large black gaps, as expected for a naive merge.

## Stage 4

Created / updated wrappers:

- `scripts/run_odm.ps1`

What was added:

- PowerShell equivalent of `run_odm.sh`
- Non-interactive Docker handling
- Output validation
- Docker exit code capture
- Clear success/failure summary for orthomosaic, DSM, and point cloud

ODM preparation:

- Copied 47 images into `data/sfm/images/`

Executed:

- `powershell -ExecutionPolicy Bypass -File .\scripts\run_odm.ps1`

Result:

- ODM produced the key deliverables despite a late report-stage failure inside the container
- Copied outputs:
  - `data/mosaic/mosaic_odm.tif`
  - `data/sfm/odm_pointcloud.laz`

Orthomosaic summary:

- Size: 1899 x 3033 px
- CRS: `EPSG:32632`
- Bounding box:
  - left: 406709.796303
  - bottom: 5375106.409639
  - right: 406747.776303
  - top: 5375167.069639

ODM registration:

- 47 / 47 images registered

Point cloud verification:

- `laspy.read()` succeeds
- Point count: 4,561,726
- XYZ bounds:
  - X: 406707.236 to 406750.001
  - Y: 5375105.01 to 5375168.827
  - Z: 139.799 to 152.13

## Stage 6

Implemented:

- `src/vegetation_index.py`

Indices generated:

- VARI
- GLI
- NGRDI

Outputs written:

- `data/mosaic/vari.tif`
- `data/mosaic/gli.tif`
- `data/mosaic/ngrdi.tif`
- `data/mosaic/vari_preview.png`
- `data/mosaic/gli_preview.png`
- `data/mosaic/ngrdi_preview.png`

Display settings:

- `RdYlGn` colormap
- display stretch clipped to `[-0.3, 0.3]`
- transparent nodata

VARI statistics:

- min: -1.0
- max: 1.0
- mean: 0.00653
- valid pixels with `VARI > 0.1`: 4.80%

Interpretation:

- Vegetation signal is concentrated along edges, planted strips, trees, and hedges
- VARI and NGRDI agree closely
- GLI is somewhat more aggressive but broadly consistent

## Interactive Viewer

Implemented:

- `src/viewer.py`
- `scripts/run_viewer.bat`

Outputs:

- `data/visualization/viewer.html`

Capabilities added:

- OpenStreetMap and Esri World Imagery basemaps
- Overlay toggles for:
  - RGB orthomosaic
  - VARI
  - GLI
  - NGRDI
  - image footprints
- Increased zoom ceiling for close inspection
- Bottom-right control panel
- Per-overlay opacity sliders
- Selected-overlay controls
- Translation-only manual overlay alignment
- Reset to original position
- Copy current dx/dy offset as JSON

Implementation note:

- The final viewer uses standard `L.imageOverlay` with custom JavaScript drag handling.
- A DistortableImage-based attempt was removed after integration problems.

## Publishing / GitHub

GitHub repository:

- `https://github.com/lceuranie/DroneImageProcessing`

What was pushed:

- Source code
- scripts
- notebook
- README updates
- self-contained `data/visualization/viewer.html`

Important publishing note:

- The GitHub repo page shows `README.md`
- GitHub Pages needs a root `index.html`

Added:

- `index.html`

Purpose:

- Redirects immediately to `data/visualization/viewer.html`

This was added specifically so GitHub Pages can open the viewer by default when publishing from the repo root.

## Key Files Added or Updated

- `src/georeference.py`
- `src/mosaic.py`
- `src/vegetation_index.py`
- `src/viewer.py`
- `tests/test_georeference.py`
- `notebooks/01_check_footprints.ipynb`
- `scripts/run_odm.ps1`
- `scripts/run_viewer.bat`
- `README.md`
- `index.html`

## Recovery Tips

If work needs to resume later, the most important entry points are:

- Stage 1:
  - `python -m src.extract_metadata --input data/raw --output data/metadata`
- Stage 2:
  - `python -m src.georeference --metadata data/metadata/metadata.json --images data/raw --output data/georeferenced`
- Stage 3:
  - `python -m src.mosaic --input data/georeferenced --output data/mosaic/mosaic_naive.tif`
- Stage 4:
  - `powershell -ExecutionPolicy Bypass -File .\scripts\run_odm.ps1`
- Stage 6:
  - `python -m src.vegetation_index --input data/mosaic/mosaic_odm.tif --output-dir data/mosaic`
- Viewer:
  - `python -m src.viewer`
  - or `scripts\run_viewer.bat`
