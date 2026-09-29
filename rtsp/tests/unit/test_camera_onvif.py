import base64
import datetime
import hashlib
import pathlib
import urllib.error
import xml.etree.ElementTree as ET

import pytest

from streaming import camera_onvif
from streaming.camera_onvif import NS

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "onvif"
RTSP_URL = "rtsp://admin:Admin%40161@192.168.1.126:554/unicaststream/1"
EMPTY_RESPONSE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope">'
    "<SOAP-ENV:Body><{op}Response/></SOAP-ENV:Body></SOAP-ENV:Envelope>")


def _fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeCamera:
    def __init__(self, clock_offset_s=0.0):
        self.clock_offset_s = clock_offset_s
        self.requests = []
        self.responses = {
            "GetServices": _fixture("GetServices.xml"),
            "GetProfiles": _fixture("GetProfiles.xml"),
            "GetVideoEncoderConfigurations": _fixture("GetVideoEncoderConfigurations.xml"),
            "media2:GetVideoEncoderConfigurations":
                _fixture("media2_GetVideoEncoderConfigurations_VEncoderToken01.xml"),
        }
        self.fail_with = None

    def ops(self):
        return [op for _, op, _, _ in self.requests]

    def request(self, op):
        return [body for _, name, _, body in self.requests if name == op]

    def _system_date_and_time(self):
        root = ET.fromstring(_fixture("GetSystemDateAndTime.xml"))
        now = (datetime.datetime.now(datetime.timezone.utc)
               + datetime.timedelta(seconds=self.clock_offset_s))
        utc = root.find(".//tt:UTCDateTime", NS)
        for path, value in (("tt:Time/tt:Hour", now.hour), ("tt:Time/tt:Minute", now.minute),
                            ("tt:Time/tt:Second", now.second), ("tt:Date/tt:Year", now.year),
                            ("tt:Date/tt:Month", now.month), ("tt:Date/tt:Day", now.day)):
            utc.find(path, NS).text = str(value)
        return ET.tostring(root)

    def __call__(self, url, envelope):
        if self.fail_with is not None:
            raise self.fail_with
        root = ET.fromstring(envelope)
        body = root.find("s:Body", NS)[0]
        namespace, op = body.tag[1:].split("}")
        self.requests.append((url, op, namespace, body))
        if op == "GetSystemDateAndTime":
            return self._system_date_and_time()
        if op == "SetSystemDateAndTime":
            utc = body.find("tds:UTCDateTime", NS)
            set_to = datetime.datetime(
                *(int(utc.find(p, NS).text) for p in (
                    "tt:Date/tt:Year", "tt:Date/tt:Month", "tt:Date/tt:Day",
                    "tt:Time/tt:Hour", "tt:Time/tt:Minute", "tt:Time/tt:Second")),
                tzinfo=datetime.timezone.utc)
            self.clock_offset_s = (set_to - datetime.datetime.now(datetime.timezone.utc)
                                   ).total_seconds()
            return EMPTY_RESPONSE.format(op=op).encode()
        if op == "GetStreamUri":
            token = body.find("trt:ProfileToken", NS).text
            return _fixture(f"GetStreamUri_{token}.xml").encode()
        if op.startswith("Set"):
            return EMPTY_RESPONSE.format(op=op).encode()
        key = f"media2:{op}" if namespace == camera_onvif.NS_TR2 else op
        return self.responses[key].encode()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("test tried to reach the network")
    monkeypatch.setattr(camera_onvif.urllib.request, "urlopen", refuse)


@pytest.fixture()
def camera(monkeypatch):
    fake = FakeCamera()
    monkeypatch.setattr(camera_onvif, "_post_soap", fake)
    return fake


def _replace_first(text, old, new):
    assert old in text
    return text.replace(old, new, 1)


def test_parse_rtsp_credentials_unquotes_password():
    assert camera_onvif.parse_rtsp_credentials(RTSP_URL) == (
        "192.168.1.126", "admin", "Admin@161", "/unicaststream/1")


def test_security_header_is_password_digest_on_camera_clock():
    nonce = b"0123456789abcdef"
    header = camera_onvif.build_security_header("admin", "Admin@161", -3600.0, nonce=nonce)
    root = ET.fromstring(f'<s:Envelope xmlns:s="{camera_onvif.NS_SOAP}">{header}</s:Envelope>')
    ns = {"wsse": camera_onvif.NS_WSSE, "wsu": camera_onvif.NS_WSU}
    token = root.find("wsse:Security/wsse:UsernameToken", ns)
    created = token.find("wsu:Created", ns).text
    password = token.find("wsse:Password", ns)

    assert token.find("wsse:Username", ns).text == "admin"
    assert password.get("Type").endswith("#PasswordDigest")
    assert base64.b64decode(token.find("wsse:Nonce", ns).text) == nonce
    assert password.text == base64.b64encode(
        hashlib.sha1(nonce + created.encode() + b"Admin@161").digest()).decode()
    created_dt = datetime.datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc)
    expected = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    assert abs((created_dt - expected).total_seconds()) < 5


def test_read_settings_from_real_camera_responses(camera):
    camera.clock_offset_s = 7200.0
    settings = camera_onvif.read_camera_stream_settings(RTSP_URL)

    assert settings["camera_clock_offset_s"] == pytest.approx(7200, abs=2)
    del settings["camera_clock_offset_s"]
    assert settings == {
        "encoding": "H264", "width": 2592, "height": 1944, "fps": 25,
        "bitrate_kbps": 16384, "gop": 25, "h264_profile": "Baseline",
        "quality": 3.0, "constant_bitrate": True,
    }
    assert camera.ops()[0] == "GetSystemDateAndTime"
    assert not any(op.startswith("Set") for op in camera.ops())


def test_read_matches_profile_by_stream_path(camera):
    settings = camera_onvif.read_camera_stream_settings(
        "rtsp://admin:Admin%40161@192.168.1.126:554/unicaststream/2")

    assert (settings["width"], settings["height"]) == (704, 576)
    assert settings["bitrate_kbps"] == 1024
    assert settings["gop"] == 50
    media2_get = camera.request("GetVideoEncoderConfigurations")[-1]
    assert media2_get.find("tr2:ConfigurationToken", NS).text == "VEncoderToken02"


def test_read_falls_back_to_first_profile(camera):
    settings = camera_onvif.read_camera_stream_settings(
        "rtsp://admin:pw@192.168.1.126:554/no/such/stream")
    assert (settings["width"], settings["height"]) == (2592, 1944)


def test_read_without_media2_has_unknown_constant_bitrate(camera):
    camera.responses["GetServices"] = camera.responses["GetServices"].replace(
        "http://www.onvif.org/ver20/media/wsdl", "http://example.invalid/not-media2")
    settings = camera_onvif.read_camera_stream_settings(RTSP_URL)
    assert settings["constant_bitrate"] is None
    assert settings["bitrate_kbps"] == 16384


@pytest.mark.parametrize("failure", [
    urllib.error.URLError("timed out"),
    urllib.error.HTTPError("http://x", 401, "Unauthorized", None, None),
    TimeoutError("timed out"),
])
def test_read_returns_none_when_camera_fails(camera, failure):
    camera.fail_with = failure
    assert camera_onvif.read_camera_stream_settings(RTSP_URL) is None


def test_read_returns_none_on_soap_fault(camera):
    camera.responses["GetProfiles"] = (
        '<?xml version="1.0"?><e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope">'
        "<e:Body><e:Fault><e:Reason><e:Text>Sender not authorized</e:Text></e:Reason>"
        "</e:Fault></e:Body></e:Envelope>")
    assert camera_onvif.read_camera_stream_settings(RTSP_URL) is None


def _recommended(**overrides):
    settings = dict(camera_onvif.RECOMMENDED_STREAM_SETTINGS,
                    h264_profile="Baseline", quality=3.0, camera_clock_offset_s=0.0)
    settings.update(overrides)
    return settings


def test_no_mismatches_for_recommended_settings():
    assert camera_onvif.describe_settings_mismatches(_recommended()) == []


def test_mismatches_bitrate_gop_and_clock():
    mismatches = camera_onvif.describe_settings_mismatches(
        _recommended(bitrate_kbps=8192, gop=50, camera_clock_offset_s=-120.0))
    assert "Bitrate 8192 kbps, recommended 16384 kbps" in mismatches
    assert any("GOP" in m and "50" in m for m in mismatches)
    assert any("clock" in m and "-120" in m for m in mismatches)
    assert len(mismatches) == 3


def test_clock_within_60_s_is_not_a_mismatch():
    assert camera_onvif.describe_settings_mismatches(
        _recommended(camera_clock_offset_s=59.0)) == []


def _canonical(element):
    return ET.canonicalize(ET.tostring(element, encoding="unicode"))


def test_apply_changes_only_gop_bitrate_fps_and_copies_the_rest(camera):
    configs = camera.responses["GetVideoEncoderConfigurations"]
    configs = _replace_first(configs, "<tt:BitrateLimit>16384</tt:BitrateLimit>",
                             "<tt:BitrateLimit>8192</tt:BitrateLimit>")
    configs = _replace_first(configs, "<tt:FrameRateLimit>25</tt:FrameRateLimit>",
                             "<tt:FrameRateLimit>15</tt:FrameRateLimit>")
    configs = _replace_first(configs, "<tt:GovLength>25</tt:GovLength>",
                             "<tt:GovLength>50</tt:GovLength>")
    camera.responses["GetVideoEncoderConfigurations"] = configs

    result = camera_onvif.apply_recommended_stream_settings(RTSP_URL)

    assert sorted(result["changed"]) == ["bitrate_kbps", "fps", "gop"]
    assert result["before"]["bitrate_kbps"] == 8192
    assert result["not_set"] == []
    set_requests = camera.request("SetVideoEncoderConfiguration")
    assert len(set_requests) == 1
    set_request = set_requests[0]
    assert set_request.tag == f"{{{camera_onvif.NS_TRT}}}SetVideoEncoderConfiguration"
    assert set_request.find("trt:ForcePersistence", NS).text == "true"

    sent = set_request.find("trt:Configuration", NS)
    original = next(c for c in ET.fromstring(configs).iter(f"{{{camera_onvif.NS_TRT}}}Configurations")
                    if c.get("token") == "VEncoderToken01")
    assert sent.attrib == original.attrib == {"token": "VEncoderToken01"}
    assert sent.find("tt:RateControl/tt:BitrateLimit", NS).text == "16384"
    assert sent.find("tt:RateControl/tt:FrameRateLimit", NS).text == "25"
    assert sent.find("tt:H264/tt:GovLength", NS).text == "25"
    assert [c.tag for c in sent] == [c.tag for c in original]
    for sent_child, original_child in zip(sent, original):
        if sent_child.tag in (f"{{{camera_onvif.NS_TT}}}RateControl",
                              f"{{{camera_onvif.NS_TT}}}H264"):
            continue
        assert _canonical(sent_child) == _canonical(original_child)
    assert sent.find("tt:RateControl/tt:EncodingInterval", NS).text == "1"
    assert sent.find("tt:H264/tt:H264Profile", NS).text == "Baseline"
    assert sent.find("tt:Resolution/tt:Width", NS).text == "2592"
    assert sent.find("tt:Encoding", NS).text == "H264"


def test_apply_sets_constant_bitrate_via_media2_copying_full_config(camera):
    media2 = _replace_first(camera.responses["media2:GetVideoEncoderConfigurations"],
                            'ConstantBitRate="true"', 'ConstantBitRate="false"')
    camera.responses["media2:GetVideoEncoderConfigurations"] = media2

    result = camera_onvif.apply_recommended_stream_settings(RTSP_URL)

    assert result["changed"] == ["constant_bitrate"]
    set_requests = camera.request("SetVideoEncoderConfiguration")
    assert len(set_requests) == 1
    assert set_requests[0].tag == f"{{{camera_onvif.NS_TR2}}}SetVideoEncoderConfiguration"
    sent = set_requests[0].find("tr2:Configuration", NS)
    original = ET.fromstring(media2).find(".//tr2:Configurations", NS)
    assert sent.attrib == original.attrib
    assert sent.find("tt:RateControl", NS).get("ConstantBitRate") == "true"
    original.find("tt:RateControl", NS).set("ConstantBitRate", "true")
    assert [_canonical(c) for c in sent] == [_canonical(c) for c in original]


def test_apply_sends_no_set_when_nothing_differs(camera):
    result = camera_onvif.apply_recommended_stream_settings(RTSP_URL)

    assert result["changed"] == []
    assert result["not_set"] == []
    assert result["after"] == result["before"]
    assert not any(op.startswith("Set") for op in camera.ops())


def test_apply_never_changes_resolution_or_codec(camera):
    configs = camera.responses["GetVideoEncoderConfigurations"]
    configs = _replace_first(configs, "<tt:Width>2592</tt:Width>", "<tt:Width>1920</tt:Width>")
    configs = _replace_first(configs, "<tt:Height>1944</tt:Height>", "<tt:Height>1080</tt:Height>")
    camera.responses["GetVideoEncoderConfigurations"] = configs

    result = camera_onvif.apply_recommended_stream_settings(RTSP_URL)

    assert result["changed"] == []
    assert not any(op.startswith("Set") for op in camera.ops())
    assert any("Resolution 1920x1080" in m
               for m in camera_onvif.describe_settings_mismatches(result["before"]))


def test_apply_reports_constant_bitrate_not_set_without_media2(camera):
    camera.responses["GetServices"] = camera.responses["GetServices"].replace(
        "http://www.onvif.org/ver20/media/wsdl", "http://example.invalid/not-media2")

    result = camera_onvif.apply_recommended_stream_settings(RTSP_URL)

    assert result["changed"] == []
    assert len(result["not_set"]) == 1 and "constant_bitrate" in result["not_set"][0]
    assert not any(op.startswith("Set") for op in camera.ops())


def test_apply_returns_none_when_camera_down(camera):
    camera.fail_with = urllib.error.URLError("unreachable")
    assert camera_onvif.apply_recommended_stream_settings(RTSP_URL) is None


def test_sync_clock_sets_manual_utc_and_keeps_timezone(camera):
    camera.clock_offset_s = -86400.0 * 30

    result = camera_onvif.sync_camera_clock(RTSP_URL)

    request = camera.request("SetSystemDateAndTime")[0]
    assert request.find("tds:DateTimeType", NS).text == "Manual"
    assert request.find("tds:DaylightSavings", NS).text == "false"
    assert request.find("tds:TimeZone/tt:TZ", NS).text == "IndiaStandardTime-5:30"
    utc = request.find("tds:UTCDateTime", NS)
    sent = datetime.datetime(
        int(utc.find("tt:Date/tt:Year", NS).text), int(utc.find("tt:Date/tt:Month", NS).text),
        int(utc.find("tt:Date/tt:Day", NS).text), int(utc.find("tt:Time/tt:Hour", NS).text),
        int(utc.find("tt:Time/tt:Minute", NS).text), int(utc.find("tt:Time/tt:Second", NS).text),
        tzinfo=datetime.timezone.utc)
    assert abs((sent - datetime.datetime.now(datetime.timezone.utc)).total_seconds()) < 5
    assert result["before_offset_s"] == pytest.approx(-86400 * 30, abs=2)
    assert abs(result["after_offset_s"]) < 3


def test_sync_clock_returns_none_when_camera_down(camera):
    camera.fail_with = urllib.error.URLError("unreachable")
    assert camera_onvif.sync_camera_clock(RTSP_URL) is None
