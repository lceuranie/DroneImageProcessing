"""Build an interactive folium viewer for the georeferenced products."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import folium
from folium.raster_layers import ImageOverlay
import rasterio
from pyproj import Transformer
from branca.element import MacroElement, Template

logger = logging.getLogger(__name__)

CRS_WORKING = "EPSG:32632"
CRS_GEOGRAPHIC = "EPSG:4326"
PROJ4_JS_CDN = "https://cdn.jsdelivr.net/npm/proj4@2.19.10/dist/proj4.js"


class ViewerControls(MacroElement):
    """Floating UI panel for opacity controls and manual alignment."""

    _template = Template(
        """
        {% macro html(this, kwargs) %}
        <div id="viewer-controls-panel" style="
            position: fixed;
            right: 18px;
            bottom: 18px;
            z-index: 10000;
            width: 320px;
            background: rgba(255, 255, 255, 0.94);
            border: 1px solid rgba(0, 0, 0, 0.25);
            border-radius: 8px;
            box-shadow: 0 4px 14px rgba(0, 0, 0, 0.16);
            padding: 12px 14px;
            font-family: Arial, sans-serif;
            font-size: 12px;
            line-height: 1.35;
        ">
            <div style="font-size: 14px; font-weight: 700; margin-bottom: 10px;">Overlay Controls</div>
            <div style="margin-bottom: 10px;">
                <div style="font-weight: 600; margin-bottom: 4px;">Selected overlay</div>
                {% for overlay in this.overlays %}
                <label style="display: block; margin-bottom: 2px;">
                    <input
                        type="radio"
                        name="selected-overlay"
                        value="{{ overlay.key }}"
                        {% if loop.first %}checked{% endif %}
                    />
                    {{ overlay.label }}
                </label>
                {% endfor %}
                <div id="active-overlay-label" style="margin-top: 6px;">
                    Selected overlay: {{ this.overlays[0].label }}
                </div>
            </div>
            {% for overlay in this.overlays %}
            <div style="margin-bottom: 10px;">
                <div style="display: flex; justify-content: space-between; gap: 8px;">
                    <span style="font-weight: 600;">{{ overlay.label }}</span>
                    <span id="offset-{{ overlay.key }}">dx 0.00 m, dy 0.00 m</span>
                </div>
                <input
                    id="opacity-{{ overlay.key }}"
                    type="range"
                    min="0"
                    max="100"
                    value="{{ overlay.opacity_percent }}"
                    style="width: 100%;"
                />
            </div>
            {% endfor %}
            <div style="margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap;">
                <button id="toggle-edit-mode" type="button">Adjust position</button>
                <button id="reset-overlays" type="button">Reset</button>
                <button id="copy-offset" type="button">Copy offset</button>
            </div>
            <div style="margin-top: 10px;">
                <a
                    href="pointcloud.html"
                    target="_blank"
                    rel="noopener"
                    style="
                        display: inline-block;
                        padding: 6px 10px;
                        border-radius: 6px;
                        background: #1f5fbf;
                        color: #fff;
                        font-weight: 600;
                        text-decoration: none;
                    "
                >
                    View 3D point cloud
                </a>
            </div>
            <div style="margin-top: 6px; color: #444;">
                Higher VARI / GLI / NGRDI values mean more vegetation.
            </div>
        </div>
        {% endmacro %}

        {% macro script(this, kwargs) %}
        (function() {
            const map = {{ this.map_name }};
            if (typeof proj4 !== "function") {
                console.warn("proj4 is unavailable; offset reporting disabled.");
                return;
            }

            proj4.defs("EPSG:32632", "+proj=utm +zone=32 +datum=WGS84 +units=m +no_defs +type=crs");

            const overlays = {
                {% for overlay in this.overlays %}
                {{ overlay.key|tojson }}: {
                    key: {{ overlay.key|tojson }},
                    label: {{ overlay.label|tojson }},
                    layer: {{ overlay.var_name }},
                    defaultOpacity: {{ overlay.opacity }},
                    originalBounds: {{ overlay.bounds|tojson }},
                    dragCleanup: null
                },
                {% endfor %}
            };

            const state = {
                editMode: false,
                activeOverlayKey: {{ this.default_active_key|tojson }},
            };

            const panel = document.getElementById("viewer-controls-panel");
            if (panel) {
                L.DomEvent.disableClickPropagation(panel);
                L.DomEvent.disableScrollPropagation(panel);
            }

            function cloneBounds(bounds) {
                return [
                    [bounds[0][0], bounds[0][1]],
                    [bounds[1][0], bounds[1][1]],
                ];
            }

            function isVisible(meta) {
                return map.hasLayer(meta.layer);
            }

            function setActiveOverlay(key) {
                if (!overlays[key]) {
                    return;
                }
                state.activeOverlayKey = key;
                const label = document.getElementById("active-overlay-label");
                if (label) {
                    label.textContent = "Selected overlay: " + overlays[key].label;
                }
                const radio = document.querySelector('input[name="selected-overlay"][value="' + key + '"]');
                if (radio) {
                    radio.checked = true;
                }
            }

            function boundsToOffset(bounds, originalBounds) {
                const currentCenter = [
                    (bounds[0][0] + bounds[1][0]) / 2.0,
                    (bounds[0][1] + bounds[1][1]) / 2.0,
                ];
                const originalCenter = [
                    (originalBounds[0][0] + originalBounds[1][0]) / 2.0,
                    (originalBounds[0][1] + originalBounds[1][1]) / 2.0,
                ];
                const currentXY = proj4("EPSG:4326", "EPSG:32632", [currentCenter[1], currentCenter[0]]);
                const originalXY = proj4("EPSG:4326", "EPSG:32632", [originalCenter[1], originalCenter[0]]);
                return {
                    dx_m: currentXY[0] - originalXY[0],
                    dy_m: currentXY[1] - originalXY[1],
                };
            }

            function updateOffsetLabel(key) {
                const meta = overlays[key];
                const bounds = meta.layer.getBounds();
                const boundsArray = [
                    [bounds.getSouthWest().lat, bounds.getSouthWest().lng],
                    [bounds.getNorthEast().lat, bounds.getNorthEast().lng],
                ];
                const offset = boundsToOffset(boundsArray, meta.originalBounds);
                const label = document.getElementById("offset-" + key);
                if (label) {
                    label.textContent = "dx " + offset.dx_m.toFixed(2) + " m, dy " + offset.dy_m.toFixed(2) + " m";
                }
                return offset;
            }

            function updateAllOffsets() {
                Object.keys(overlays).forEach(updateOffsetLabel);
            }

            function detachDragHandlers(meta) {
                if (meta.dragCleanup) {
                    meta.dragCleanup();
                    meta.dragCleanup = null;
                }
            }

            function attachDragHandlers(meta) {
                detachDragHandlers(meta);
                if (!state.editMode || !isVisible(meta) || !meta.layer._image) {
                    return;
                }

                const image = meta.layer._image;
                let dragging = false;
                let startLatLng = null;
                let dragStartBounds = null;

                function onMouseDown(event) {
                    if (!state.editMode || state.activeOverlayKey !== meta.key) {
                        return;
                    }
                    dragging = true;
                    setActiveOverlay(meta.key);
                    startLatLng = map.mouseEventToLatLng(event);
                    const bounds = meta.layer.getBounds();
                    dragStartBounds = [
                        [bounds.getSouthWest().lat, bounds.getSouthWest().lng],
                        [bounds.getNorthEast().lat, bounds.getNorthEast().lng],
                    ];
                    map.dragging.disable();
                    event.preventDefault();
                    event.stopPropagation();
                }

                function onMouseMove(event) {
                    if (!dragging || !startLatLng || !dragStartBounds) {
                        return;
                    }
                    const currentLatLng = map.mouseEventToLatLng(event);
                    const dLat = currentLatLng.lat - startLatLng.lat;
                    const dLng = currentLatLng.lng - startLatLng.lng;
                    const newBounds = [
                        [dragStartBounds[0][0] + dLat, dragStartBounds[0][1] + dLng],
                        [dragStartBounds[1][0] + dLat, dragStartBounds[1][1] + dLng],
                    ];
                    meta.layer.setBounds(newBounds);
                    updateOffsetLabel(meta.key);
                    event.preventDefault();
                    event.stopPropagation();
                }

                function endDrag() {
                    if (!dragging) {
                        return;
                    }
                    dragging = false;
                    startLatLng = null;
                    dragStartBounds = null;
                    map.dragging.enable();
                }

                image.addEventListener("mousedown", onMouseDown);
                document.addEventListener("mousemove", onMouseMove);
                document.addEventListener("mouseup", endDrag);
                image.style.cursor = "move";

                meta.dragCleanup = function() {
                    image.removeEventListener("mousedown", onMouseDown);
                    document.removeEventListener("mousemove", onMouseMove);
                    document.removeEventListener("mouseup", endDrag);
                    image.style.cursor = "";
                    endDrag();
                };
            }

            function syncEditMode() {
                Object.values(overlays).forEach((meta) => {
                    attachDragHandlers(meta);
                });
            }

            function toggleEditMode() {
                state.editMode = !state.editMode;
                const button = document.getElementById("toggle-edit-mode");
                if (button) {
                    button.textContent = state.editMode ? "Exit edit mode" : "Adjust position";
                }
                syncEditMode();
            }

            function resetOverlays() {
                Object.values(overlays).forEach((meta) => {
                    meta.layer.setBounds(cloneBounds(meta.originalBounds));
                    meta.layer.setOpacity(meta.defaultOpacity);
                    const slider = document.getElementById("opacity-" + meta.key);
                    if (slider) {
                        slider.value = String(Math.round(meta.defaultOpacity * 100));
                    }
                });
                updateAllOffsets();
                syncEditMode();
            }

            function copyOffset() {
                const meta = overlays[state.activeOverlayKey];
                const payload = updateOffsetLabel(meta.key);
                const jsonPayload = JSON.stringify({
                    dx_m: Number(payload.dx_m.toFixed(2)),
                    dy_m: Number(payload.dy_m.toFixed(2)),
                });

                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(jsonPayload);
                } else {
                    const temp = document.createElement("textarea");
                    temp.value = jsonPayload;
                    document.body.appendChild(temp);
                    temp.select();
                    document.execCommand("copy");
                    document.body.removeChild(temp);
                }
            }

            Object.values(overlays).forEach((meta) => {
                const slider = document.getElementById("opacity-" + meta.key);
                if (slider) {
                    slider.addEventListener("input", (event) => {
                        const opacity = Number(event.target.value) / 100.0;
                        meta.layer.setOpacity(opacity);
                    });
                }

                meta.layer.on("click", () => setActiveOverlay(meta.key));
            });

            document.querySelectorAll('input[name="selected-overlay"]').forEach((radio) => {
                radio.addEventListener("change", (event) => {
                    setActiveOverlay(event.target.value);
                    syncEditMode();
                });
            });

            map.on("overlayadd overlayremove", () => {
                syncEditMode();
            });

            const toggleButton = document.getElementById("toggle-edit-mode");
            if (toggleButton) {
                toggleButton.addEventListener("click", toggleEditMode);
            }

            const resetButton = document.getElementById("reset-overlays");
            if (resetButton) {
                resetButton.addEventListener("click", resetOverlays);
            }

            const copyButton = document.getElementById("copy-offset");
            if (copyButton) {
                copyButton.addEventListener("click", copyOffset);
            }

            updateAllOffsets();
            setActiveOverlay(state.activeOverlayKey);
            syncEditMode();
        })();
        {% endmacro %}
        """
    )

    def __init__(self, overlays: list[dict[str, Any]], map_name: str) -> None:
        super().__init__()
        self._name = "ViewerControls"
        self.overlays = overlays
        self.map_name = map_name
        self.default_active_key = overlays[0]["key"]


def resolve_input_path(*candidates: Path) -> Path:
    """Return the first existing input path from a list of candidates."""
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(", ".join(str(candidate) for candidate in candidates))


def transform_bounds_to_wgs84(bounds: rasterio.coords.BoundingBox) -> list[list[float]]:
    """Convert UTM bounds to Leaflet lat/lon bounds."""
    transformer = Transformer.from_crs(CRS_WORKING, CRS_GEOGRAPHIC, always_xy=True)
    west, south = transformer.transform(bounds.left, bounds.bottom)
    east, north = transformer.transform(bounds.right, bounds.top)
    return [[south, west], [north, east]]


def get_orthomosaic_bounds_and_center(
    mosaic_path: Path,
) -> tuple[list[list[float]], list[float]]:
    """Read the orthomosaic bounds and centroid in WGS84."""
    with rasterio.open(mosaic_path) as dataset:
        leaflet_bounds = transform_bounds_to_wgs84(dataset.bounds)

    south, west = leaflet_bounds[0]
    north, east = leaflet_bounds[1]
    center = [(south + north) / 2.0, (west + east) / 2.0]
    return leaflet_bounds, center


def load_footprints_geojson(footprints_path: Path) -> dict[str, Any]:
    """Load and reproject the Stage 2 footprints into WGS84 GeoJSON."""
    transformer = Transformer.from_crs(CRS_WORKING, CRS_GEOGRAPHIC, always_xy=True)
    geojson = json.loads(footprints_path.read_text(encoding="utf-8"))

    for feature in geojson.get("features", []):
        rings = feature["geometry"]["coordinates"]
        transformed_rings = []
        for ring in rings:
            transformed_ring = []
            for x, y in ring:
                lon, lat = transformer.transform(x, y)
                transformed_ring.append([lon, lat])
            transformed_rings.append(transformed_ring)
        feature["geometry"]["coordinates"] = transformed_rings

    return geojson


def add_external_dependencies(map_object: folium.Map) -> None:
    """Load third-party JS required by the viewer."""
    root = map_object.get_root()
    root.header.add_child(folium.Element(f'<script src="{PROJ4_JS_CDN}"></script>'))


def add_legend(map_object: folium.Map) -> None:
    """Add a small vegetation-index legend to the map."""
    legend_html = """
    <div style="
        position: fixed;
        bottom: 18px;
        left: 18px;
        z-index: 9999;
        background: rgba(255, 255, 255, 0.92);
        border: 1px solid rgba(0, 0, 0, 0.2);
        border-radius: 6px;
        padding: 10px 12px;
        font-family: Arial, sans-serif;
        font-size: 12px;
        line-height: 1.35;
        max-width: 240px;
    ">
        <div style="font-weight: 700; margin-bottom: 6px;">Vegetation Indices</div>
        <div><span style="font-weight: 700;">VARI</span>, <span style="font-weight: 700;">GLI</span>, <span style="font-weight: 700;">NGRDI</span></div>
        <div>Higher values = more vegetation</div>
        <div>Use the bottom-right panel to adjust opacity and alignment.</div>
    </div>
    """
    map_object.get_root().html.add_child(folium.Element(legend_html))


def build_viewer(
    mosaic_path: Path,
    preview_rgb_path: Path,
    vari_preview_path: Path,
    gli_preview_path: Path,
    ngrdi_preview_path: Path,
    footprints_path: Path,
    output_path: Path,
) -> None:
    """Create the interactive HTML viewer."""
    overlay_bounds, center = get_orthomosaic_bounds_and_center(mosaic_path)
    footprint_geojson = load_footprints_geojson(footprints_path)

    viewer = folium.Map(
        location=center,
        zoom_start=19,
        max_zoom=22,
        tiles=None,
    )
    add_external_dependencies(viewer)

    folium.TileLayer(
        tiles="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        name="OpenStreetMap",
        overlay=False,
        control=True,
        max_zoom=22,
        max_native_zoom=19,
    ).add_to(viewer)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Esri World Imagery",
        overlay=False,
        control=True,
        max_zoom=22,
        max_native_zoom=19,
    ).add_to(viewer)

    overlay_specs = [
        {
            "key": "rgb",
            "label": "RGB orthomosaic",
            "image": preview_rgb_path,
            "opacity": 1.0,
            "show": True,
        },
        {
            "key": "vari",
            "label": "VARI",
            "image": vari_preview_path,
            "opacity": 0.7,
            "show": False,
        },
        {
            "key": "gli",
            "label": "GLI",
            "image": gli_preview_path,
            "opacity": 0.7,
            "show": False,
        },
        {
            "key": "ngrdi",
            "label": "NGRDI",
            "image": ngrdi_preview_path,
            "opacity": 0.7,
            "show": False,
        },
    ]

    control_specs: list[dict[str, Any]] = []
    for spec in overlay_specs:
        layer = ImageOverlay(
            name=spec["label"],
            image=str(spec["image"]),
            bounds=overlay_bounds,
            opacity=spec["opacity"],
            interactive=True,
            cross_origin=False,
            show=spec["show"],
            max_zoom=22,
        )
        layer.add_to(viewer)
        control_specs.append(
            {
                "key": spec["key"],
                "label": spec["label"],
                "opacity": spec["opacity"],
                "opacity_percent": round(spec["opacity"] * 100),
                "bounds": overlay_bounds,
                "var_name": layer.get_name(),
            }
        )

    folium.GeoJson(
        footprint_geojson,
        name="Image footprints",
        style_function=lambda _feature: {
            "color": "#1f77b4",
            "weight": 1,
            "fillOpacity": 0.0,
        },
        tooltip=folium.GeoJsonTooltip(fields=["filename"]),
        show=False,
    ).add_to(viewer)

    add_legend(viewer)
    folium.LayerControl(position="topright", collapsed=False).add_to(viewer)
    viewer.add_child(ViewerControls(control_specs, viewer.get_name()))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    viewer.save(str(output_path))
    logger.info("Wrote interactive viewer to %s", output_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/visualization/viewer.html"),
        help="Output HTML path",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        mosaic_path = resolve_input_path(Path("data/mosaic/mosaic_odm.tif"))
        preview_rgb_path = resolve_input_path(Path("data/mosaic/preview_odm.png"))
        vari_preview_path = resolve_input_path(Path("data/mosaic/vari_preview.png"))
        gli_preview_path = resolve_input_path(Path("data/mosaic/gli_preview.png"))
        ngrdi_preview_path = resolve_input_path(Path("data/mosaic/ngrdi_preview.png"))
        footprints_path = resolve_input_path(
            Path("data/georeferenced/footprints.geojson"),
            Path("..") / ".." / "data/georeferenced/footprints.geojson",
        )
    except FileNotFoundError as exc:
        raise SystemExit(f"Missing required input(s): {exc}") from exc

    build_viewer(
        mosaic_path=mosaic_path,
        preview_rgb_path=preview_rgb_path,
        vari_preview_path=vari_preview_path,
        gli_preview_path=gli_preview_path,
        ngrdi_preview_path=ngrdi_preview_path,
        footprints_path=footprints_path,
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
