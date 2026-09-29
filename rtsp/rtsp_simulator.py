import sys
import subprocess
import time
import zipfile
import tarfile
import urllib.request
import json
import signal
import os
import platform
from pathlib import Path

_IS_WINDOWS = sys.platform == "win32"
_IS_MAC     = sys.platform == "darwin"
_ARCH       = platform.machine().lower()
_MEDIAMTX_BIN_NAME = "mediamtx.exe" if _IS_WINDOWS else "mediamtx"

SCRIPT_DIR   = Path(__file__).parent.resolve()
BIN_DIR      = SCRIPT_DIR / "bin" / "mediamtx"
MEDIAMTX_EXE = BIN_DIR / _MEDIAMTX_BIN_NAME
MEDIAMTX_CFG = BIN_DIR / "mediamtx.yml"
MEDIAMTX_ZIP = BIN_DIR / "mediamtx_download"

GITHUB_API = "https://api.github.com/repos/aler9/mediamtx/releases/latest"

RTSP_URL = "rtsp://localhost:8554/test"

MEDIAMTX_YML = """\
logLevel: info
paths:
  test:
"""

_ffmpeg_proc:   "subprocess.Popen | None" = None
_mediamtx_proc: "subprocess.Popen | None" = None


def _die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _check_ffmpeg() -> None:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    if _IS_MAC:
        _mac_candidates = [
            Path("/usr/local/bin/ffmpeg"),
            Path("/opt/homebrew/bin/ffmpeg"),
            Path("/opt/local/bin/ffmpeg"),
        ]
        for candidate in _mac_candidates:
            if candidate.exists():
                parent = str(candidate.parent)
                os.environ["PATH"] = parent + os.pathsep + os.environ.get("PATH", "")
                print(f"FFmpeg found at {candidate} — added to PATH for this session.")
                return
        _die(
            "FFmpeg not found.\n"
            "Install it with Homebrew:  brew install ffmpeg\n"
            "Then rerun this script."
        )

    _win_roots = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages",
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")),
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")),
        Path(os.environ.get("USERPROFILE", "")) / "scoop" / "shims",
    ]
    if _IS_WINDOWS:
        for root in _win_roots:
            if not root.exists():
                continue
            for exe in root.rglob("ffmpeg.exe"):
                os.environ["PATH"] = str(exe.parent) + os.pathsep + os.environ.get("PATH", "")
                print(f"FFmpeg found at {exe} — added to PATH for this session.")
                return
        print("FFmpeg not found. Attempting install via winget…")
        subprocess.run(["winget", "install", "--id", "Gyan.FFmpeg", "-e"], check=False)
        for root in _win_roots:
            if not root.exists():
                continue
            for exe in root.rglob("ffmpeg.exe"):
                os.environ["PATH"] = str(exe.parent) + os.pathsep + os.environ.get("PATH", "")
                return
        _die(
            "FFmpeg installed but could not be located automatically.\n"
            "Please add ffmpeg/bin to your PATH manually, then reopen the terminal."
        )

    _die(
        "FFmpeg not found.\n"
        "Install it with your package manager, e.g.:\n"
        "  Ubuntu/Debian: sudo apt install ffmpeg\n"
        "  Fedora:        sudo dnf install ffmpeg\n"
        "Then rerun this script."
    )


def _mediamtx_asset_info() -> tuple:
    if _IS_WINDOWS:
        return ("windows_amd64", False)
    if _IS_MAC:
        arch = "arm64" if _ARCH in ("arm64", "aarch64") else "amd64"
        return (f"darwin_{arch}", True)
    arch = "arm64" if _ARCH in ("arm64", "aarch64") else "amd64"
    return (f"linux_{arch}", True)


def _download_mediamtx() -> None:
    print("Fetching MediaMTX release info from GitHub…")
    try:
        req = urllib.request.Request(
            GITHUB_API,
            headers={"User-Agent": "rtsp-simulator/1.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            release = json.loads(resp.read())
    except Exception as exc:
        _die(
            f"Failed to fetch MediaMTX release info: {exc}\n"
            "Download manually from https://github.com/aler9/mediamtx/releases "
            f"and place the '{_MEDIAMTX_BIN_NAME}' binary in ./bin/mediamtx/"
        )

    keyword, is_tar = _mediamtx_asset_info()
    asset_url  = None
    asset_name = None
    for asset in release.get("assets", []):
        name: str = asset["name"].lower()
        if keyword in name and name.endswith(".tar.gz" if is_tar else ".zip"):
            asset_url  = asset["browser_download_url"]
            asset_name = asset["name"]
            break

    if not asset_url:
        _die(
            f"Could not find a '{keyword}' asset in the latest MediaMTX release.\n"
            "Download manually from https://github.com/aler9/mediamtx/releases "
            f"and place '{_MEDIAMTX_BIN_NAME}' in ./bin/mediamtx/"
        )

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    ext          = ".tar.gz" if is_tar else ".zip"
    download_tmp = BIN_DIR / ("mediamtx_download" + ext)

    print(f"Downloading {asset_name}…")
    try:
        def _progress(block_num, block_size, total_size):
            if total_size > 0:
                pct  = min(block_num * block_size / total_size * 100, 100)
                done = int(pct / 2)
                print(f"\r  [{'#' * done}{' ' * (50 - done)}] {pct:.0f}%", end="", flush=True)
        urllib.request.urlretrieve(asset_url, download_tmp, reporthook=_progress)
        print()
    except Exception as exc:
        _die(f"\nDownload failed: {exc}")

    print("Extracting…")
    try:
        if is_tar:
            with tarfile.open(download_tmp, "r:gz") as tf:
                for member in tf.getmembers():
                    if member.name.endswith("mediamtx") and not member.isdir():
                        member.name = _MEDIAMTX_BIN_NAME
                        tf.extract(member, path=BIN_DIR)
                        break
                else:
                    _die("'mediamtx' binary not found inside the downloaded archive.")
        else:
            with zipfile.ZipFile(download_tmp) as zf:
                for member in zf.namelist():
                    if member.lower().endswith("mediamtx.exe"):
                        target = BIN_DIR / "mediamtx.exe"
                        with zf.open(member) as src, open(target, "wb") as dst:
                            dst.write(src.read())
                        break
                else:
                    _die("mediamtx.exe not found inside the downloaded zip.")
    except Exception as exc:
        _die(f"Extraction failed: {exc}")
    finally:
        download_tmp.unlink(missing_ok=True)

    if not _IS_WINDOWS:
        MEDIAMTX_EXE.chmod(MEDIAMTX_EXE.stat().st_mode | 0o111)

    print(f"MediaMTX installed to {MEDIAMTX_EXE}")


def _ensure_mediamtx() -> None:
    if not MEDIAMTX_EXE.exists():
        _download_mediamtx()

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    MEDIAMTX_CFG.write_text(MEDIAMTX_YML, encoding="utf-8")


def _pick_video_via_dialog() -> "str | None":
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Select a video file",
            filetypes=[
                ("Video files", "*.mp4 *.mov *.mkv *.avi"),
                ("MP4", "*.mp4"),
                ("MOV", "*.mov"),
                ("All files", "*.*"),
            ],
        )
        root.destroy()
        return path if path else None
    except Exception as exc:
        _die(f"Could not open file dialog: {exc}\nPass the video path as a command-line argument.")


def _resolve_video(argv: list) -> Path:
    if argv:
        p = Path(argv[0])
        if not p.exists():
            _die(f"File not found: {p}")
        if p.suffix.lower() not in (".mp4", ".mov", ".mkv", ".avi"):
            print(f"Warning: {p.suffix} is not a tested format — proceeding anyway.")
        return p.resolve()

    chosen = _pick_video_via_dialog()
    if not chosen:
        print("No file selected. Exiting.")
        sys.exit(0)
    return Path(chosen).resolve()


def _start_mediamtx() -> subprocess.Popen:
    proc = subprocess.Popen(
        [str(MEDIAMTX_EXE), str(MEDIAMTX_CFG)],
        cwd=str(BIN_DIR),
    )
    time.sleep(2)
    if proc.poll() is not None:
        _die("MediaMTX failed to start — check output above.")
    return proc


def _start_ffmpeg(video: Path) -> subprocess.Popen:
    cmd = [
        "ffmpeg",
        "-re",
        "-stream_loop", "-1",
        "-i", str(video),
        "-c:v", "copy",
        "-an",
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        RTSP_URL,
    ]
    proc = subprocess.Popen(cmd)
    time.sleep(3)
    if proc.poll() is not None:
        _die("FFmpeg failed to start — check output above.")
    return proc


def _shutdown(sig=None, frame=None) -> None:
    print("\nStopping…")
    if _ffmpeg_proc and _ffmpeg_proc.poll() is None:
        _ffmpeg_proc.terminate()
        try:
            _ffmpeg_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _ffmpeg_proc.kill()
    if _mediamtx_proc and _mediamtx_proc.poll() is None:
        _mediamtx_proc.terminate()
        try:
            _mediamtx_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _mediamtx_proc.kill()
    print("Stream stopped.")
    sys.exit(0)


def main() -> None:
    global _ffmpeg_proc, _mediamtx_proc

    video = _resolve_video(sys.argv[1:])

    print(f"Source video : {video}")
    print(f"Platform     : {sys.platform} / {_ARCH}")

    _check_ffmpeg()
    _ensure_mediamtx()

    print("Starting MediaMTX…")
    _mediamtx_proc = _start_mediamtx()

    print("Starting FFmpeg stream…")
    _ffmpeg_proc = _start_ffmpeg(video)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)

    print()
    print(f"  RTSP stream live at: {RTSP_URL}")
    print( "  Pravah app  →  enter this as the camera URL")
    print( "  VLC / mpv   →  Media > Open Network Stream > paste URL")
    print( "  Press Ctrl+C to stop.")
    print()

    try:
        while True:
            time.sleep(1)

            if _ffmpeg_proc.poll() is not None:
                print("\nFFmpeg exited unexpectedly — check output above.", file=sys.stderr)
                _shutdown()

            if _mediamtx_proc.poll() is not None:
                print("\nMediaMTX exited unexpectedly — check output above.", file=sys.stderr)
                _shutdown()

    except KeyboardInterrupt:
        _shutdown()


if __name__ == "__main__":
    main()
