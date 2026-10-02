import copy
import pathlib
import sys

import pytest

RTSP_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(RTSP_DIR) not in sys.path:
    sys.path.insert(0, str(RTSP_DIR))


@pytest.fixture()
def client():
    import app_stream
    with app_stream.app.test_client() as c:
        yield c


@pytest.fixture()
def clean_state():
    from streaming.session import (session, session_lock, _snapshot_rec,
                                   _snapshot_rec_lock, _SESSION_DEFAULTS)
    import static_mode

    snapshot_defaults = {
        "status": None, "path": None, "error": None, "clip_index": 0,
        "total_clips": 0, "saved_paths": [], "folder": None, "attempt": None,
    }

    def _reset():
        with session_lock:
            session.clear()
            session.update(copy.deepcopy(_SESSION_DEFAULTS))
        with _snapshot_rec_lock:
            _snapshot_rec.clear()
            _snapshot_rec.update(copy.deepcopy(snapshot_defaults))
        with static_mode.jobs_lock:
            static_mode.jobs.clear()

    _reset()
    yield
    _reset()
