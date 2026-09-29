import pytest
from flask import Flask

from camera_routes import camera_bp
from streaming import camera_onvif

RTSP_URL = "rtsp://admin:Admin%40161@192.168.1.126:554/unicaststream/1"
SETTINGS = dict(camera_onvif.RECOMMENDED_STREAM_SETTINGS, bitrate_kbps=8192,
                h264_profile="Baseline", quality=3.0, camera_clock_offset_s=0.0)


@pytest.fixture()
def camera_client(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("test tried to reach the network")
    monkeypatch.setattr(camera_onvif, "_post_soap", refuse)
    app = Flask(__name__)
    app.register_blueprint(camera_bp)
    with app.test_client() as client:
        yield client


def test_settings_ok(camera_client, monkeypatch):
    monkeypatch.setattr(camera_onvif, "read_camera_stream_settings", lambda url: SETTINGS)
    response = camera_client.get("/api/camera/settings", query_string={"rtsp_url": RTSP_URL})
    body = response.get_json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["settings"] == SETTINGS
    assert body["recommended"] == camera_onvif.RECOMMENDED_STREAM_SETTINGS
    assert body["mismatches"] == ["Bitrate 8192 kbps, recommended 16384 kbps"]


def test_settings_camera_down(camera_client, monkeypatch):
    monkeypatch.setattr(camera_onvif, "read_camera_stream_settings", lambda url: None)
    response = camera_client.get("/api/camera/settings", query_string={"rtsp_url": RTSP_URL})
    assert response.status_code == 200
    assert response.get_json() == {"ok": False, "error": "camera did not answer"}


@pytest.mark.parametrize("rtsp_url", [
    None, "", "http://admin:pw@host/x", "rtsp://host/unicaststream/1",
    "rtsp://admin@host/unicaststream/1",
])
def test_settings_bad_url_is_400(camera_client, rtsp_url):
    query = {} if rtsp_url is None else {"rtsp_url": rtsp_url}
    response = camera_client.get("/api/camera/settings", query_string=query)
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


WRITE_ROUTES = [
    ("/api/camera/settings/apply", "apply_recommended_stream_settings",
     {"before": SETTINGS, "after": SETTINGS, "changed": [], "not_set": []}),
    ("/api/camera/clock/sync", "sync_camera_clock",
     {"before_offset_s": -500.0, "after_offset_s": 0.0}),
]


@pytest.mark.parametrize("path,service,result", WRITE_ROUTES)
@pytest.mark.parametrize("payload", [
    {"rtsp_url": RTSP_URL},
    {"rtsp_url": RTSP_URL, "confirm": False},
    {"rtsp_url": RTSP_URL, "confirm": "true"},
    {"rtsp_url": RTSP_URL, "confirm": 1},
    None,
])
def test_write_without_confirm_is_400(camera_client, monkeypatch, path, service, result, payload):
    called = []
    monkeypatch.setattr(camera_onvif, service, lambda url: called.append(url))
    response = camera_client.post(path, json=payload) if payload is not None \
        else camera_client.post(path)
    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert called == []


@pytest.mark.parametrize("path,service,result", WRITE_ROUTES)
def test_write_bad_url_is_400(camera_client, monkeypatch, path, service, result):
    called = []
    monkeypatch.setattr(camera_onvif, service, lambda url: called.append(url))
    response = camera_client.post(path, json={"rtsp_url": "rtsp://host/1", "confirm": True})
    assert response.status_code == 400
    assert called == []


@pytest.mark.parametrize("path,service,result", WRITE_ROUTES)
def test_write_ok(camera_client, monkeypatch, path, service, result):
    called = []
    monkeypatch.setattr(camera_onvif, service, lambda url: called.append(url) or result)
    response = camera_client.post(path, json={"rtsp_url": RTSP_URL, "confirm": True})
    assert response.status_code == 200
    assert response.get_json() == {"ok": True, **result}
    assert called == [RTSP_URL]


@pytest.mark.parametrize("path,service,result", WRITE_ROUTES)
def test_write_camera_down(camera_client, monkeypatch, path, service, result):
    monkeypatch.setattr(camera_onvif, service, lambda url: None)
    response = camera_client.post(path, json={"rtsp_url": RTSP_URL, "confirm": True})
    assert response.status_code == 200
    assert response.get_json() == {"ok": False, "error": "camera did not answer"}
