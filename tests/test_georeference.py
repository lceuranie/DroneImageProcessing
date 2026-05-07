from __future__ import annotations

from src.georeference import compute_gsd


def test_compute_gsd_matches_hand_calculation() -> None:
    """20 m altitude, 6 mm sensor, 3 mm focal, 4000 px width -> 1 cm/px."""
    gsd_m_per_pixel = compute_gsd(
        sensor_width_mm=6.0,
        relative_altitude_m=20.0,
        focal_length_mm=3.0,
        image_width_px=4000,
    )

    assert gsd_m_per_pixel == 0.01
