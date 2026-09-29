import json
import pathlib

import numpy as np
import pytest

pyorc = pytest.importorskip("pyorc")

from piv.defaults import INTRINSICS_RNG_SEED
from piv.pipeline import _seeded_numpy_rng

CONFIG = json.loads(
    (pathlib.Path(__file__).resolve().parents[1] / "golden" / "kunah_config.json").read_text())


def _build_fx():
    g = CONFIG["gcps"]
    gcps = {
        "src": g["src"],
        "dst": [[float(p[0]), float(p[1])] for p in g["dst"]],
        "z_0": float(g["z_0"]),
        "h_ref": float(CONFIG["h_a"]),
    }
    with _seeded_numpy_rng(INTRINSICS_RNG_SEED):
        cc = pyorc.CameraConfig(
            height=CONFIG["frame_height"], width=CONFIG["frame_width"], gcps=gcps,
            lens_position=list(CONFIG["lens_position"]), resolution=0.05, window_size=10)
    return float(cc.camera_matrix[0][0])


def test_fx_is_identical_under_different_global_rng_states():
    np.random.seed(11)
    fx_a = _build_fx()
    np.random.seed(148)
    np.random.rand(7)
    fx_b = _build_fx()
    assert fx_a == fx_b


def test_global_rng_state_is_restored_after_build():
    np.random.seed(5)
    _build_fx()
    drawn_after_build = np.random.rand()
    np.random.seed(5)
    drawn_fresh = np.random.rand()
    assert drawn_after_build == drawn_fresh


def test_seeded_block_restores_state_even_on_exception():
    np.random.seed(7)
    with pytest.raises(RuntimeError):
        with _seeded_numpy_rng(INTRINSICS_RNG_SEED):
            raise RuntimeError("boom")
    drawn_after = np.random.rand()
    np.random.seed(7)
    assert drawn_after == np.random.rand()
