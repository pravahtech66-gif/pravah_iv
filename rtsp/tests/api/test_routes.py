import threading

import pytest

import app_stream
from streaming.session import session, session_lock, _snapshot_rec


@pytest.fixture()
def fake_hw(monkeypatch, tmp_path):
    monkeypatch.setattr(app_stream, "_recorder_thread", lambda *a, **k: None)
    monkeypatch.setattr(app_stream, "_processor_thread", lambda *a, **k: None)
    monkeypatch.setattr(app_stream, "_run_snapshot_recording", lambda *a, **k: None)

    monkeypatch.setattr(app_stream, "_check_ffmpeg", lambda: True)
    monkeypatch.setattr(app_stream, "_check_desktop_writable", lambda: (True, ""))

    results_root = tmp_path / "results"
    stream_tmp = results_root / "stream_tmp"
    desktop = tmp_path / "Desktop"
    results_root.mkdir(parents=True, exist_ok=True)
    stream_tmp.mkdir(parents=True, exist_ok=True)
    desktop.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(app_stream, "RESULTS_ROOT", results_root)
    monkeypatch.setattr(app_stream, "STREAM_TMP", stream_tmp)
    monkeypatch.setattr(app_stream, "DESKTOP", desktop)


def _set_status(status):
    with session_lock:
        session["status"] = status


def _get_session_value(key):
    with session_lock:
        return session[key]


def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_index_returns_html_200(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type


def test_start_missing_rtsp_url_400(client, clean_state, fake_hw):
    resp = client.post("/api/stream/start", json={})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "rtsp_url is required"


def test_start_while_running_returns_409(client, clean_state, fake_hw):
    _set_status("running")
    resp = client.post("/api/stream/start", json={"rtsp_url": "rtsp://x"})
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "Session already running"


def test_start_clamps_low_batch_duration_to_30(client, clean_state, fake_hw):
    resp = client.post(
        "/api/stream/start",
        json={"rtsp_url": "rtsp://x", "batch_duration_s": 5},
    )
    assert resp.status_code == 200
    assert _get_session_value("batch_duration_s") == 30
    status = client.get("/api/stream/status").get_json()
    assert status["batch_duration_s"] == 30


def test_start_clamps_high_batch_duration_to_600(client, clean_state, fake_hw):
    resp = client.post(
        "/api/stream/start",
        json={"rtsp_url": "rtsp://x", "batch_duration_s": 9999},
    )
    assert resp.status_code == 200
    assert _get_session_value("batch_duration_s") == 600


def test_start_non_dict_config_400(client, clean_state, fake_hw):
    resp = client.post(
        "/api/stream/start",
        json={"rtsp_url": "rtsp://x", "config": "not-a-dict"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "config must be a JSON object"


def test_start_happy_path_sets_running_and_events(client, clean_state, fake_hw):
    resp = client.post("/api/stream/start", json={"rtsp_url": "rtsp://cam"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert isinstance(body["session_id"], str) and body["session_id"]

    assert _get_session_value("status") == "running"
    assert _get_session_value("rtsp_url") == "rtsp://cam"
    stop_event = _get_session_value("_stop_event")
    batch_ready_event = _get_session_value("_batch_ready_event")
    assert isinstance(stop_event, threading.Event)
    assert isinstance(batch_ready_event, threading.Event)
    assert not stop_event.is_set()


def test_stop_before_any_manual_recording_stops_the_session(client, clean_state, fake_hw):
    stop_event = threading.Event()
    _set_status("running")
    with session_lock:
        session["_stop_event"] = stop_event
        assert "is_recording" not in session

    resp = client.post("/api/stream/stop", json={})
    assert resp.status_code == 200
    assert _get_session_value("status") == "stopping"
    assert stop_event.is_set()


def test_stop_no_active_session_400(client, clean_state, fake_hw):
    resp = client.post("/api/stream/stop", json={})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "No active session"


def test_stop_running_sets_stopping_and_stop_event(client, clean_state, fake_hw):
    stop_event = threading.Event()
    _set_status("running")
    with session_lock:
        session["_stop_event"] = stop_event
        session["is_recording"] = False

    resp = client.post("/api/stream/stop", json={})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert _get_session_value("status") == "stopping"
    assert stop_event.is_set()


def test_config_missing_key_400(client, clean_state, fake_hw):
    resp = client.patch("/api/stream/config", json={})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "batch_duration_s required"


def test_config_clamps_low(client, clean_state, fake_hw):
    resp = client.patch("/api/stream/config", json={"batch_duration_s": 1})
    assert resp.status_code == 200
    assert _get_session_value("batch_duration_s") == 30
    assert _get_session_value("_drop_current_batch") is True


def test_config_clamps_high(client, clean_state, fake_hw):
    resp = client.patch("/api/stream/config", json={"batch_duration_s": 100000})
    assert resp.status_code == 200
    assert _get_session_value("batch_duration_s") == 600
    assert _get_session_value("_drop_current_batch") is True


def test_save_batch_not_running_400(client, clean_state, fake_hw):
    resp = client.post("/api/stream/save_batch")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "No active session"


def test_save_batch_running_queues_then_conflicts(client, clean_state, fake_hw):
    _set_status("running")

    resp1 = client.post("/api/stream/save_batch")
    assert resp1.status_code == 200
    assert resp1.get_json()["ok"] is True
    assert _get_session_value("_save_next_batch") is True

    resp2 = client.post("/api/stream/save_batch")
    assert resp2.status_code == 409
    assert resp2.get_json()["error"] == "A save is already queued"


def test_status_strips_underscore_keys_and_adds_derived(client, clean_state, fake_hw):
    snap = client.get("/api/stream/status").get_json()
    assert not any(k.startswith("_") for k in snap)
    assert "save_next_queued" in snap
    assert "total_batches_processed" in snap
    assert snap["total_batches_processed"] == 0
    assert snap["save_next_queued"] is False


def test_status_warn_flags_are_consume_once(client, clean_state, fake_hw):
    with session_lock:
        session["warn_batch_dropped"] = True
        session["warn_duration_changed"] = True

    first = client.get("/api/stream/status").get_json()
    assert first["warn_batch_dropped"] is True
    assert first["warn_duration_changed"] is True

    second = client.get("/api/stream/status").get_json()
    assert second["warn_batch_dropped"] is False
    assert second["warn_duration_changed"] is False


def test_record_snapshot_missing_url_400(client, clean_state, fake_hw):
    resp = client.post("/api/stream/record_snapshot", json={})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "rtsp_url required"


def test_record_snapshot_while_recording_409(client, clean_state, fake_hw):
    with app_stream._snapshot_rec_lock:
        _snapshot_rec["status"] = "recording"
    resp = client.post("/api/stream/record_snapshot", json={"rtsp_url": "rtsp://x"})
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "Snapshot recording already in progress"


def test_record_snapshot_happy_path(client, clean_state, fake_hw):
    resp = client.post("/api/stream/record_snapshot", json={"rtsp_url": "rtsp://cam"})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    with app_stream._snapshot_rec_lock:
        assert _snapshot_rec["status"] == "recording"
        assert _snapshot_rec["total_clips"] == app_stream.SNAPSHOT_CLIP_COUNT


def test_snapshot_status_returns_snapshot_rec_shape(client, clean_state, fake_hw):
    snap = client.get("/api/stream/snapshot_status").get_json()
    assert snap["status"] is None
    for key in ("status", "path", "error", "clip_index", "total_clips",
                "saved_paths", "folder", "attempt"):
        assert key in snap


def test_probe_without_url_returns_ok_false_json(client, clean_state, fake_hw):
    resp = client.get("/api/stream/probe")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error"] == "rtsp_url query param required"


def test_snapshot_without_url_400(client, clean_state, fake_hw):
    resp = client.get("/api/stream/snapshot")
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_live_without_url_400(client, clean_state, fake_hw):
    resp = client.get("/api/stream/live")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "rtsp_url required"


def test_cors_allowed_origin_is_echoed(client):
    resp = client.get("/health", headers={"Origin": "http://localhost:5001"})
    assert resp.headers.get("Access-Control-Allow-Origin") == "http://localhost:5001"
    assert resp.headers.get("Vary") == "Origin"


def test_cors_disallowed_origin_absent(client):
    resp = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "Access-Control-Allow-Origin" not in resp.headers


@pytest.fixture()
def sensor_cfg_path(monkeypatch, tmp_path):
    path = tmp_path / "sensor_config.json"
    monkeypatch.setattr(app_stream, "SENSOR_CONFIG_PATH", path)
    return path


def test_sensor_config_get_empty_returns_empty_dict(client, sensor_cfg_path):
    assert not sensor_cfg_path.exists()
    resp = client.get("/api/sensor/config")
    assert resp.status_code == 200
    assert resp.get_json() == {}


def test_sensor_config_post_then_get_roundtrip(client, sensor_cfg_path):
    payload = {"protocol": "modbus_tcp", "tcp_host": "10.0.0.5", "address": 100}
    post = client.post("/api/sensor/config", json=payload)
    assert post.status_code == 200
    assert post.get_json()["ok"] is True
    assert sensor_cfg_path.exists()

    got = client.get("/api/sensor/config")
    assert got.status_code == 200
    assert got.get_json() == payload


def test_sensor_config_post_non_dict_400(client, sensor_cfg_path):
    resp = client.post("/api/sensor/config", json=[1, 2, 3])
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Expected JSON object"


def test_sensor_test_ok_path(client, monkeypatch):
    monkeypatch.setattr(app_stream, "read_sensor_once", lambda cfg: (1.5, 150))
    resp = client.post("/api/sensor/test", json={"unit": "cm"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["value_m"] == 1.5
    assert body["value_raw"] == 150
    assert body["unit"] == "cm"


def test_sensor_test_runtime_error_path(client, monkeypatch):
    def _boom(cfg):
        raise RuntimeError("no sensor")

    monkeypatch.setattr(app_stream, "read_sensor_once", _boom)
    resp = client.post("/api/sensor/test", json={})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error"] == "no sensor"


def test_sensor_ports_returns_fake_list(client, monkeypatch):
    fake_ports = [{"port": "COM3", "description": "USB Serial"}]
    monkeypatch.setattr(app_stream, "list_com_ports", lambda: fake_ports)
    resp = client.get("/api/sensor/ports")
    assert resp.status_code == 200
    assert resp.get_json() == {"ports": fake_ports}
