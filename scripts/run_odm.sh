#!/usr/bin/env bash
# Run OpenDroneMap on the dataset via Docker.
# Stage 4 of the pipeline — produces a true orthomosaic, DSM, and point cloud.
#
# Expects:  data/sfm/images/  ← copy or symlink your raw .JPGs here first
# Outputs:  data/sfm/odm_orthophoto/odm_orthophoto.tif
#           data/sfm/odm_dem/dsm.tif
#           data/sfm/odm_georeferenced_model/odm_georeferenced_model.laz
#
# Requires: Docker

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${PROJECT_ROOT}/data"
PROJECT_NAME="sfm"

if [ ! -d "${DATA_DIR}/${PROJECT_NAME}/images" ]; then
    echo "Error: ${DATA_DIR}/${PROJECT_NAME}/images does not exist." >&2
    echo "Copy or symlink your DJI .JPG files there first:" >&2
    echo "    mkdir -p ${DATA_DIR}/${PROJECT_NAME}/images" >&2
    echo "    cp ${DATA_DIR}/raw/*.JPG ${DATA_DIR}/${PROJECT_NAME}/images/" >&2
    exit 1
fi

docker run -ti --rm \
    -v "${DATA_DIR}":/datasets \
    opendronemap/odm \
    --project-path /datasets "${PROJECT_NAME}" \
    --orthophoto-resolution 2 \
    --dsm \
    --pc-las \
    --feature-quality high \
    --use-exif

echo
echo "Done. Key outputs:"
echo "  ${DATA_DIR}/${PROJECT_NAME}/odm_orthophoto/odm_orthophoto.tif"
echo "  ${DATA_DIR}/${PROJECT_NAME}/odm_dem/dsm.tif"
echo "  ${DATA_DIR}/${PROJECT_NAME}/odm_georeferenced_model/odm_georeferenced_model.laz"
