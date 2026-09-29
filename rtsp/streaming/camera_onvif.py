import base64
import copy
import datetime
import hashlib
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Optional

from streaming.config import _log
from streaming.models.onvif_target import OnvifTarget

SOAP_TIMEOUT_S = 5
ONVIF_PORT = 80

NS_SOAP = "http://www.w3.org/2003/05/soap-envelope"
NS_TT = "http://www.onvif.org/ver10/schema"
NS_TDS = "http://www.onvif.org/ver10/device/wsdl"
NS_TRT = "http://www.onvif.org/ver10/media/wsdl"
NS_TR2 = "http://www.onvif.org/ver20/media/wsdl"
NS_WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
NS_WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
_PASSWORD_DIGEST = ("http://docs.oasis-open.org/wss/2004/01/"
                    "oasis-200401-wss-username-token-profile-1.0#PasswordDigest")
_NONCE_ENCODING = ("http://docs.oasis-open.org/wss/2004/01/"
                   "oasis-200401-wss-soap-message-security-1.0#Base64Binary")
NS = {"s": NS_SOAP, "tt": NS_TT, "tds": NS_TDS, "trt": NS_TRT, "tr2": NS_TR2}

for _prefix, _uri in (("tt", NS_TT), ("tds", NS_TDS), ("trt", NS_TRT), ("tr2", NS_TR2)):
    ET.register_namespace(_prefix, _uri)

RECOMMENDED_STREAM_SETTINGS = {
    "encoding": "H264",
    "width": 2592,
    "height": 1944,
    "fps": 25,
    "gop": 25,
    "bitrate_kbps": 16384,
    "constant_bitrate": True,
}
MAX_CLOCK_OFFSET_S = 60


class OnvifError(Exception):
    pass


def parse_rtsp_credentials(rtsp_url: str) -> tuple:
    parts = urllib.parse.urlsplit(rtsp_url)
    return (parts.hostname,
            urllib.parse.unquote(parts.username or ""),
            urllib.parse.unquote(parts.password or ""),
            parts.path)


def _post_soap(url: str, envelope: bytes) -> bytes:
    request = urllib.request.Request(
        url, data=envelope,
        headers={"Content-Type": "application/soap+xml; charset=utf-8"})
    with urllib.request.urlopen(request, timeout=SOAP_TIMEOUT_S) as response:
        return response.read()


def build_security_header(username: str, password: str, clock_offset_s: float,
                          nonce: Optional[bytes] = None) -> str:
    nonce = nonce if nonce is not None else os.urandom(16)
    camera_now = (datetime.datetime.now(datetime.timezone.utc)
                  + datetime.timedelta(seconds=clock_offset_s))
    created = camera_now.strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = base64.b64encode(hashlib.sha1(
        nonce + created.encode("utf-8") + password.encode("utf-8")).digest()).decode()
    return (
        f'<wsse:Security xmlns:wsse="{NS_WSSE}" xmlns:wsu="{NS_WSU}" s:mustUnderstand="1">'
        f"<wsse:UsernameToken>"
        f"<wsse:Username>{_xml_escape(username)}</wsse:Username>"
        f'<wsse:Password Type="{_PASSWORD_DIGEST}">{digest}</wsse:Password>'
        f'<wsse:Nonce EncodingType="{_NONCE_ENCODING}">{base64.b64encode(nonce).decode()}</wsse:Nonce>'
        f"<wsu:Created>{created}</wsu:Created>"
        f"</wsse:UsernameToken></wsse:Security>")


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _soap_call(url: str, body_xml: str, target: Optional[OnvifTarget]) -> ET.Element:
    header = ""
    if target is not None:
        header = build_security_header(target.username, target.password,
                                       target.clock_offset_s)
    envelope = (f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<s:Envelope xmlns:s="{NS_SOAP}" xmlns:tt="{NS_TT}" xmlns:tds="{NS_TDS}" '
                f'xmlns:trt="{NS_TRT}" xmlns:tr2="{NS_TR2}">'
                f"<s:Header>{header}</s:Header><s:Body>{body_xml}</s:Body></s:Envelope>")
    root = ET.fromstring(_post_soap(url, envelope.encode("utf-8")))
    body = root.find("s:Body", NS)
    if body is None or len(body) == 0:
        raise OnvifError("SOAP response has no Body")
    if body[0].tag == f"{{{NS_SOAP}}}Fault":
        raise OnvifError("SOAP Fault: " + "".join(body[0].itertext()).strip())
    return body[0]


def _device_url(host: str) -> str:
    return f"http://{host}:{ONVIF_PORT}/onvif/device_service"


def _text(element: ET.Element, path: str) -> str:
    found = element.find(path, NS)
    if found is None or found.text is None:
        raise OnvifError(f"missing {path}")
    return found.text


def _read_system_date_and_time(host: str) -> tuple:
    response = _soap_call(_device_url(host), "<tds:GetSystemDateAndTime/>", None)
    local_utc = datetime.datetime.now(datetime.timezone.utc)
    utc = response.find("tds:SystemDateAndTime/tt:UTCDateTime", NS)
    if utc is None:
        raise OnvifError("camera did not report UTCDateTime")
    camera_utc = datetime.datetime(
        int(_text(utc, "tt:Date/tt:Year")), int(_text(utc, "tt:Date/tt:Month")),
        int(_text(utc, "tt:Date/tt:Day")), int(_text(utc, "tt:Time/tt:Hour")),
        int(_text(utc, "tt:Time/tt:Minute")), int(_text(utc, "tt:Time/tt:Second")),
        tzinfo=datetime.timezone.utc)
    tz = response.find("tds:SystemDateAndTime/tt:TimeZone/tt:TZ", NS)
    return (camera_utc - local_utc).total_seconds(), (tz.text if tz is not None else None)


def _connect(rtsp_url: str) -> OnvifTarget:
    host, username, password, _ = parse_rtsp_credentials(rtsp_url)
    offset_s, _ = _read_system_date_and_time(host)
    return OnvifTarget(host, username, password, offset_s)


def _service_urls(target: OnvifTarget) -> dict:
    response = _soap_call(
        _device_url(target.host),
        "<tds:GetServices><tds:IncludeCapability>false</tds:IncludeCapability></tds:GetServices>",
        target)
    return {_text(service, "tds:Namespace"): _text(service, "tds:XAddr")
            for service in response.findall("tds:Service", NS)}


def _find_profile(target: OnvifTarget, media_url: str, stream_path: str) -> ET.Element:
    profiles = _soap_call(media_url, "<trt:GetProfiles/>", target).findall("trt:Profiles", NS)
    if not profiles:
        raise OnvifError("camera reported no media profiles")
    for profile in profiles:
        response = _soap_call(
            media_url,
            "<trt:GetStreamUri><trt:StreamSetup><tt:Stream>RTP-Unicast</tt:Stream>"
            "<tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport></trt:StreamSetup>"
            f"<trt:ProfileToken>{profile.get('token')}</trt:ProfileToken></trt:GetStreamUri>",
            target)
        if urllib.parse.urlsplit(_text(response, "trt:MediaUri/tt:Uri")).path == stream_path:
            return profile
    return profiles[0]


def _read_encoder_config(target: OnvifTarget, media_url: str, token: str) -> ET.Element:
    response = _soap_call(media_url, "<trt:GetVideoEncoderConfigurations/>", target)
    for configuration in response.findall("trt:Configurations", NS):
        if configuration.get("token") == token:
            return configuration
    raise OnvifError(f"encoder configuration {token} not found")


def _read_media2_encoder_config(target: OnvifTarget, media2_url: str,
                                token: str) -> ET.Element:
    response = _soap_call(
        media2_url,
        f"<tr2:GetVideoEncoderConfigurations><tr2:ConfigurationToken>{token}"
        f"</tr2:ConfigurationToken></tr2:GetVideoEncoderConfigurations>",
        target)
    configuration = response.find("tr2:Configurations", NS)
    if configuration is None:
        raise OnvifError(f"Media2 encoder configuration {token} not found")
    return configuration


def _optional_int(element: ET.Element, path: str) -> Optional[int]:
    found = element.find(path, NS)
    return int(found.text) if found is not None and found.text else None


def _settings_from_config(config: ET.Element, media2_config: Optional[ET.Element],
                          clock_offset_s: float) -> dict:
    constant_bitrate = None
    if media2_config is not None:
        rate_control = media2_config.find("tt:RateControl", NS)
        if rate_control is not None and rate_control.get("ConstantBitRate") is not None:
            constant_bitrate = rate_control.get("ConstantBitRate") == "true"
    quality = config.find("tt:Quality", NS)
    profile = config.find("tt:H264/tt:H264Profile", NS)
    return {
        "encoding": _text(config, "tt:Encoding"),
        "width": int(_text(config, "tt:Resolution/tt:Width")),
        "height": int(_text(config, "tt:Resolution/tt:Height")),
        "fps": _optional_int(config, "tt:RateControl/tt:FrameRateLimit"),
        "bitrate_kbps": _optional_int(config, "tt:RateControl/tt:BitrateLimit"),
        "gop": _optional_int(config, "tt:H264/tt:GovLength"),
        "h264_profile": profile.text if profile is not None else None,
        "quality": float(quality.text) if quality is not None else None,
        "constant_bitrate": constant_bitrate,
        "camera_clock_offset_s": round(clock_offset_s, 1),
    }


def _read_state(rtsp_url: str) -> dict:
    target = _connect(rtsp_url)
    services = _service_urls(target)
    media_url = services.get(NS_TRT)
    if media_url is None:
        raise OnvifError("camera has no Media service")
    media2_url = services.get(NS_TR2)
    profile = _find_profile(target, media_url, parse_rtsp_credentials(rtsp_url)[3])
    encoder = profile.find("tt:VideoEncoderConfiguration", NS)
    if encoder is None:
        raise OnvifError(f"profile {profile.get('token')} has no video encoder")
    token = encoder.get("token")
    config = _read_encoder_config(target, media_url, token)
    media2_config = None
    if media2_url is not None:
        try:
            media2_config = _read_media2_encoder_config(target, media2_url, token)
        except (OSError, ET.ParseError, OnvifError) as exc:
            _log.warning("ONVIF Media2 read failed on %s: %s", target.host, exc)
    return {
        "target": target, "media_url": media_url, "media2_url": media2_url,
        "token": token, "config": config, "media2_config": media2_config,
        "settings": _settings_from_config(config, media2_config, target.clock_offset_s),
    }


def read_camera_stream_settings(rtsp_url: str) -> Optional[dict]:
    try:
        return _read_state(rtsp_url)["settings"]
    except Exception as exc:
        _log.warning("ONVIF settings read failed on %s: %s",
                     parse_rtsp_credentials(rtsp_url)[0], exc)
        return None


def describe_settings_mismatches(settings: dict) -> list:
    rec = RECOMMENDED_STREAM_SETTINGS
    mismatches = []
    if settings["encoding"] != rec["encoding"]:
        mismatches.append(f"Codec {settings['encoding']}, recommended {rec['encoding']} "
                          f"(not changed automatically)")
    if (settings["width"], settings["height"]) != (rec["width"], rec["height"]):
        mismatches.append(
            f"Resolution {settings['width']}x{settings['height']}, recommended "
            f"{rec['width']}x{rec['height']} (not changed automatically: "
            f"it would invalidate the GCP calibration)")
    if settings["fps"] != rec["fps"]:
        mismatches.append(f"Frame rate {settings['fps']} fps, recommended {rec['fps']} fps")
    if settings["gop"] != rec["gop"]:
        mismatches.append(f"Keyframe interval (GOP) {settings['gop']} frames, "
                          f"recommended {rec['gop']} frames")
    if settings["bitrate_kbps"] != rec["bitrate_kbps"]:
        mismatches.append(f"Bitrate {settings['bitrate_kbps']} kbps, "
                          f"recommended {rec['bitrate_kbps']} kbps")
    if settings["constant_bitrate"] is False:
        mismatches.append("Variable bitrate, recommended constant bitrate")
    offset = settings["camera_clock_offset_s"]
    if abs(offset) > MAX_CLOCK_OFFSET_S:
        mismatches.append(f"Camera clock off by {offset:+.0f} s "
                          f"(more than {MAX_CLOCK_OFFSET_S} s)")
    return mismatches


_VER10_WRITABLE_FIELDS = {
    "fps": "tt:RateControl/tt:FrameRateLimit",
    "bitrate_kbps": "tt:RateControl/tt:BitrateLimit",
    "gop": "tt:H264/tt:GovLength",
}


def _build_set_encoder_request(config: ET.Element, new_values: dict) -> str:
    configuration = copy.deepcopy(config)
    configuration.tag = f"{{{NS_TRT}}}Configuration"
    configuration.tail = None
    for key, value in new_values.items():
        configuration.find(_VER10_WRITABLE_FIELDS[key], NS).text = str(value)
    request = ET.Element(f"{{{NS_TRT}}}SetVideoEncoderConfiguration")
    request.append(configuration)
    ET.SubElement(request, f"{{{NS_TRT}}}ForcePersistence").text = "true"
    return ET.tostring(request, encoding="unicode")


def _build_media2_set_encoder_request(media2_config: ET.Element) -> str:
    configuration = copy.deepcopy(media2_config)
    configuration.tag = f"{{{NS_TR2}}}Configuration"
    configuration.tail = None
    configuration.find("tt:RateControl", NS).set("ConstantBitRate", "true")
    request = ET.Element(f"{{{NS_TR2}}}SetVideoEncoderConfiguration")
    request.append(configuration)
    return ET.tostring(request, encoding="unicode")


def apply_recommended_stream_settings(rtsp_url: str) -> Optional[dict]:
    host = parse_rtsp_credentials(rtsp_url)[0]
    try:
        state = _read_state(rtsp_url)
        before = state["settings"]
        target = state["target"]
        changed, not_set = [], []

        new_values = {}
        for key, path in _VER10_WRITABLE_FIELDS.items():
            if before[key] == RECOMMENDED_STREAM_SETTINGS[key]:
                continue
            if state["config"].find(path, NS) is None:
                not_set.append(f"{key}: camera configuration has no {path}")
            else:
                new_values[key] = RECOMMENDED_STREAM_SETTINGS[key]
        if new_values:
            _soap_call(state["media_url"],
                       _build_set_encoder_request(state["config"], new_values), target)
            changed.extend(new_values)

        if before["constant_bitrate"] is not True:
            if state["media2_url"] is None or state["media2_config"] is None:
                not_set.append("constant_bitrate: camera Media2 service not available")
            else:
                try:
                    fresh = _read_media2_encoder_config(target, state["media2_url"],
                                                        state["token"])
                    _soap_call(state["media2_url"],
                               _build_media2_set_encoder_request(fresh), target)
                    changed.append("constant_bitrate")
                except (OSError, ET.ParseError, OnvifError) as exc:
                    not_set.append(f"constant_bitrate: {exc}")

        after = before if not changed else read_camera_stream_settings(rtsp_url)
        return {"before": before, "after": after, "changed": changed, "not_set": not_set}
    except Exception as exc:
        _log.warning("ONVIF apply settings failed on %s: %s", host, exc)
        return None


def _build_set_date_time_request(utc_now: datetime.datetime, tz: Optional[str]) -> str:
    time_zone = (f"<tds:TimeZone><tt:TZ>{_xml_escape(tz)}</tt:TZ></tds:TimeZone>"
                 if tz is not None else "")
    return ("<tds:SetSystemDateAndTime>"
            "<tds:DateTimeType>Manual</tds:DateTimeType>"
            "<tds:DaylightSavings>false</tds:DaylightSavings>"
            f"{time_zone}"
            "<tds:UTCDateTime>"
            f"<tt:Time><tt:Hour>{utc_now.hour}</tt:Hour><tt:Minute>{utc_now.minute}</tt:Minute>"
            f"<tt:Second>{utc_now.second}</tt:Second></tt:Time>"
            f"<tt:Date><tt:Year>{utc_now.year}</tt:Year><tt:Month>{utc_now.month}</tt:Month>"
            f"<tt:Day>{utc_now.day}</tt:Day></tt:Date>"
            "</tds:UTCDateTime></tds:SetSystemDateAndTime>")


def sync_camera_clock(rtsp_url: str) -> Optional[dict]:
    host, username, password, _ = parse_rtsp_credentials(rtsp_url)
    try:
        before_offset_s, tz = _read_system_date_and_time(host)
        target = OnvifTarget(host, username, password, before_offset_s)
        _soap_call(_device_url(host),
                   _build_set_date_time_request(
                       datetime.datetime.now(datetime.timezone.utc), tz),
                   target)
        after_offset_s, _ = _read_system_date_and_time(host)
        return {"before_offset_s": round(before_offset_s, 1),
                "after_offset_s": round(after_offset_s, 1)}
    except Exception as exc:
        _log.warning("ONVIF clock sync failed on %s: %s", host, exc)
        return None
