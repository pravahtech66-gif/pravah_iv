import pytest

from piv.auto_params import compute_auto_resolution

SQUARE_PIXELS = [[0, 0], [100, 0], [100, 100], [0, 100]]


def test_resolution_from_planar_gcps_is_sqrt_of_world_area_over_pixel_area():
    world = [[0, 0], [2, 0], [2, 2], [0, 2]]
    assert compute_auto_resolution(SQUARE_PIXELS, world) == pytest.approx(0.02)


def test_resolution_from_gcps_with_z_uses_the_horizontal_footprint():
    world = [[0, 0, 0.3], [2, 0, 0.3], [2, 2, 0.1], [0, 2, 0.1]]
    assert compute_auto_resolution(SQUARE_PIXELS, world) == pytest.approx(0.02)


def test_resolution_is_clipped_to_one_centimetre_for_dense_gcps():
    world = [[0, 0, 0], [0.1, 0, 0], [0.1, 0.1, 0], [0, 0.1, 0]]
    assert compute_auto_resolution(SQUARE_PIXELS, world) == pytest.approx(0.01)


def test_computed_params_summary_survives_a_stdout_that_cannot_encode_unicode(monkeypatch):
    import io
    import sys

    import numpy as np

    from piv.auto_params import _print_computed_params

    class AsciiOnlyStdout(io.TextIOBase):
        def __init__(self):
            self.chunks = []

        def write(self, s):
            s.encode("ascii")
            self.chunks.append(s)
            return len(s)

    fake = AsciiOnlyStdout()
    monkeypatch.setattr(sys, "stdout", fake)

    _print_computed_params(
        workflow="quasi_automated", resolution=0.01, framestep=8, fps=59.7, alpha=0.85,
        piv_window=16, piv_overlap=8, corr_min=0.3, s2n_min=2.0, gcp_mode="2D", n_pairs=4,
        h_a=0.0, z_0=0.0, speed_filt=np.array([[0.1, 0.2]]), x_coords=np.array([0.0, 1.0]),
        y_coords=np.array([0.0]), discharge_result={}, sa_params=None, config={},
        is_auto=True, estimated_speed_ms=0.1,
    )

    text = "".join(fake.chunks)
    assert "COMPUTED PARAMETERS SUMMARY" in text
    assert "═" not in text
