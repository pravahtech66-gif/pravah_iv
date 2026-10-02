import time

import pytest

import app_stream
import streaming.manual_recorder as manual_recorder
from streaming.models.piece import Piece
from streaming.models.recorder_status import RecorderStatus
from streaming.session import session, session_lock


class FakeRecorder:
    def __init__(self, url=""):
        self.url = url
        self.started_urls = []
        self.holds = []

    def start_recording(self, rtsp_url):
        self.started_urls.append(rtsp_url)
        self.url = rtsp_url

    def hold_pieces_since(self, wall_ts):
        self.holds.append(wall_ts)

    def recording_url(self):
        return self.url

    def describe_recorder_status(self):
        return RecorderStatus(running=True, rtsp_url=self.url, buffered_s=120.0,
                              newest_piece_age_s=1.5, preview_age_s=0.4, restarts=2,
                              last_error="no new video for 15s — stream stalled")


@pytest.fixture()
def fake_recorder(monkeypatch):
    rec = FakeRecorder()
    monkeypatch.setattr(app_stream, "get_camera_recorder", lambda: rec)
    monkeypatch.setattr(manual_recorder, "get_camera_recorder", lambda: rec)
    return rec


@pytest.fixture()
def fake_cutter(monkeypatch, tmp_path):
    calls = {"cut": [], "saved": [tmp_path / "recording_x.mp4"]}

    def cut_window_clips(start_wall, end_wall, dest):
        calls["cut"].append((start_wall, end_wall, dest))
        return calls["saved"]

    future_piece = Piece(path=tmp_path / "p.mkv", run_id="1", start_s=0.0, end_s=10.0,
                         wall_start=time.time() + 60)
    monkeypatch.setattr(manual_recorder, "cut_window_clips", cut_window_clips)
    monkeypatch.setattr(manual_recorder, "list_finished_pieces", lambda: [future_piece])
    monkeypatch.setattr(manual_recorder, "write_clip_manifest", lambda *a, **k: None)
    return calls


def test_recorder_status_masks_password(client, fake_recorder):
    fake_recorder.url = "rtsp://admin:Admin%40161@192.168.1.126:554/unicaststream/1"
    resp = client.get("/api/stream/recorder_status")
    assert resp.status_code == 200
    assert resp.get_json() == {
        "running": True,
        "rtsp_url": "rtsp://admin:***@192.168.1.126:554/unicaststream/1",
        "buffered_s": 120.0,
        "newest_piece_age_s": 1.5,
        "preview_age_s": 0.4,
        "restarts": 2,
        "last_error": "no new video for 15s — stream stalled",
    }


def test_recorder_status_url_without_password_unchanged(client, fake_recorder):
    fake_recorder.url = "rtsp://localhost:8554/test"
    assert client.get("/api/stream/recorder_status").get_json()["rtsp_url"] == fake_recorder.url


def test_record_start_with_body_url_holds_buffer_and_sets_session(client, clean_state, fake_recorder):
    before = time.time()
    resp = client.post("/api/stream/record/start", json={"rtsp_url": "rtsp://cam"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert fake_recorder.started_urls == ["rtsp://cam"]
    assert len(fake_recorder.holds) == 1 and fake_recorder.holds[0] >= before
    with session_lock:
        assert session["is_recording"] is True
        assert session["rec_started_at"] == fake_recorder.holds[0]
        assert session["rec_file"] == body["file"]
        assert session["rec_file"].startswith("recording_") and session["rec_file"].endswith(".mp4")


def test_record_start_without_body_uses_session_url(client, clean_state, fake_recorder):
    with session_lock:
        session["rtsp_url"] = "rtsp://session-cam"
    resp = client.post("/api/stream/record/start")
    assert resp.status_code == 200
    assert fake_recorder.started_urls == ["rtsp://session-cam"]


def test_record_start_without_body_falls_back_to_recorder_url(client, clean_state, fake_recorder):
    fake_recorder.url = "rtsp://already-recording"
    resp = client.post("/api/stream/record/start")
    assert resp.status_code == 200
    assert fake_recorder.started_urls == ["rtsp://already-recording"]


def test_record_start_without_any_url_400(client, clean_state, fake_recorder):
    resp = client.post("/api/stream/record/start")
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    assert fake_recorder.started_urls == []


def test_record_start_twice_409(client, clean_state, fake_recorder):
    client.post("/api/stream/record/start", json={"rtsp_url": "rtsp://cam"})
    resp = client.post("/api/stream/record/start", json={"rtsp_url": "rtsp://cam"})
    assert resp.status_code == 409
    assert resp.get_json()["ok"] is False


def test_record_stop_cuts_window_and_releases_hold(client, clean_state, fake_recorder, fake_cutter):
    client.post("/api/stream/record/start", json={"rtsp_url": "rtsp://cam"})
    with session_lock:
        started_at = session["rec_started_at"]
        rec_file = session["rec_file"]

    resp = client.post("/api/stream/record/stop")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "file": "recording_x.mp4"}

    (start_wall, end_wall, dest) = fake_cutter["cut"][0]
    assert start_wall == started_at and end_wall >= started_at
    assert dest.name == rec_file
    assert fake_recorder.holds[-1] is None
    with session_lock:
        assert session["is_recording"] is False


def test_record_stop_joins_multiple_parts(client, clean_state, fake_recorder, fake_cutter, tmp_path):
    fake_cutter["saved"] = [tmp_path / "rec_part1.mp4", tmp_path / "rec_part2.mp4"]
    client.post("/api/stream/record/start", json={"rtsp_url": "rtsp://cam"})
    resp = client.post("/api/stream/record/stop")
    assert resp.get_json() == {"ok": True, "file": "rec_part1.mp4, rec_part2.mp4"}


def test_record_stop_nothing_saved_is_not_ok(client, clean_state, fake_recorder, fake_cutter):
    fake_cutter["saved"] = []
    client.post("/api/stream/record/start", json={"rtsp_url": "rtsp://cam"})
    resp = client.post("/api/stream/record/stop")
    assert resp.get_json()["ok"] is False
    assert fake_recorder.holds[-1] is None


def test_record_stop_when_not_recording_400(client, clean_state, fake_recorder, fake_cutter):
    resp = client.post("/api/stream/record/stop")
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    assert fake_cutter["cut"] == []
