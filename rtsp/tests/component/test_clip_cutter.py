import csv
import pathlib
import shutil
import subprocess
import time

import pytest

import streaming.recorder as recorder
from streaming.clip_cutter import (
    group_contiguous_pieces,
    join_pieces_into_clip,
    select_latest_clip_pieces,
)
from streaming.clip_integrity import measure_clip_timing, read_frame_timestamps
from streaming.models.piece import Piece

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                  reason="ffmpeg/ffprobe not on PATH")

FPS = 25


def _piece(run_id, start_s, length_s=10.0, wall_start=None):
    return Piece(path=pathlib.Path(f"{run_id}_{start_s}.mkv"), run_id=run_id,
                 start_s=start_s, end_s=start_s + length_s,
                 wall_start=1000.0 + start_s if wall_start is None else wall_start)


def test_contiguous_pieces_of_one_run_form_one_chain():
    pieces = [_piece("a", 0), _piece("a", 10), _piece("a", 20)]
    assert group_contiguous_pieces(pieces) == [pieces]


def test_gap_splits_chain():
    pieces = [_piece("a", 0), _piece("a", 10), _piece("a", 25)]
    assert group_contiguous_pieces(pieces) == [pieces[:2], pieces[2:]]


def test_new_run_splits_chain_even_if_times_line_up():
    pieces = [_piece("a", 0), _piece("b", 10)]
    assert group_contiguous_pieces(pieces) == [[pieces[0]], [pieces[1]]]


def test_select_takes_newest_pieces_that_cover_duration():
    pieces = [_piece("a", s) for s in (0, 10, 20, 30, 40)]
    assert select_latest_clip_pieces(pieces, 25) == pieces[2:]


def test_select_skips_newest_chain_when_too_short():
    old = [_piece("a", s) for s in (0, 10, 20)]
    new = [_piece("b", s, wall_start=2000.0 + s) for s in (0, 10)]
    assert select_latest_clip_pieces(old + new, 30) == old


def test_select_returns_none_when_nothing_long_enough():
    pieces = [_piece("a", 0), _piece("a", 10), _piece("a", 30)]
    assert select_latest_clip_pieces(pieces, 25) is None


def test_select_not_before_ignores_older_pieces():
    pieces = [_piece("a", s) for s in (0, 10, 20, 30)]
    assert select_latest_clip_pieces(pieces, 20, not_before_wall=1015) == pieces[2:]
    assert select_latest_clip_pieces(pieces, 30, not_before_wall=1015) is None


def _record_fake_run(buffer_dir: pathlib.Path, run_id: str, seconds: int, piece_s: int) -> None:
    list_path = buffer_dir / f"run_{run_id}.csv"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"testsrc=size=160x120:rate={FPS}", "-t", str(seconds),
         "-c:v", "libx264", "-g", str(FPS), "-bf", "0",
         "-pix_fmt", "yuv420p",
         "-f", "segment", "-segment_time", str(piece_s), "-segment_format", "matroska",
         "-reset_timestamps", "1", "-segment_list", str(list_path),
         "-segment_list_type", "csv", str(buffer_dir / "raw_%03d.mkv")],
        check=True, timeout=60)
    rows = list(csv.reader(list_path.open(newline="")))
    base = time.time() - 600
    for index, row in enumerate(rows):
        stamp = time.strftime(recorder.PIECE_NAME_FORMAT, time.localtime(base + index * piece_s))
        new_name = f"{stamp}_{run_id}.mkv"
        (buffer_dir / row[0]).rename(buffer_dir / new_name)
        row[0] = new_name
    with list_path.open("w", newline="") as f:
        csv.writer(f).writerows(rows)


@needs_ffmpeg
def test_joined_pieces_have_every_frame_and_no_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder, "BUFFER_DIR", tmp_path)
    _record_fake_run(tmp_path, "1700000000", seconds=8, piece_s=2)

    pieces = recorder.list_finished_pieces()
    assert len(pieces) == 3
    assert len(group_contiguous_pieces(pieces)) == 1

    clip = tmp_path / "clip.mp4"
    assert join_pieces_into_clip(pieces, clip)

    timing = measure_clip_timing(read_frame_timestamps(clip))
    assert timing["frames"] == 3 * 2 * FPS
    assert timing["missing_frames"] == 0
    assert timing["max_gap_s"] == pytest.approx(1 / FPS, abs=1e-3)


@needs_ffmpeg
def test_join_with_duration_trims_to_requested_length(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder, "BUFFER_DIR", tmp_path)
    _record_fake_run(tmp_path, "1700000000", seconds=8, piece_s=2)

    clip = tmp_path / "clip.mp4"
    assert join_pieces_into_clip(recorder.list_finished_pieces(), clip, duration_s=4)
    assert measure_clip_timing(read_frame_timestamps(clip))["frames"] == 4 * FPS
