import re
import time

import pytest

from streaming.session import (
    _MAX_LOG_ENTRIES,
    _MAX_RESULTS_IN_POLL,
    _reset_session,
    _session_snapshot,
    _slog,
    _SESSION_DEFAULTS,
    session,
    session_lock,
)


class TestSessionSnapshot:
    def test_strips_every_underscore_prefixed_key(self, clean_state):
        snap = _session_snapshot()
        assert all(not k.startswith("_") for k in snap.keys())
        with session_lock:
            assert any(k.startswith("_") for k in session.keys())

    def test_includes_total_batches_processed(self, clean_state):
        with session_lock:
            session["results"] = [{"batch": i} for i in range(5)]
        snap = _session_snapshot()
        assert snap["total_batches_processed"] == 5

    def test_includes_save_next_queued_from_internal_flag(self, clean_state):
        with session_lock:
            session["_save_next_batch"] = True
        snap = _session_snapshot()
        assert snap["save_next_queued"] is True

    def test_save_next_queued_false_by_default(self, clean_state):
        snap = _session_snapshot()
        assert snap["save_next_queued"] is False

    def test_results_trimmed_to_last_50(self, clean_state):
        with session_lock:
            session["results"] = [{"batch": i} for i in range(75)]
        snap = _session_snapshot()
        assert len(snap["results"]) == _MAX_RESULTS_IN_POLL == 50
        assert snap["results"][0] == {"batch": 25}
        assert snap["results"][-1] == {"batch": 74}
        assert snap["total_batches_processed"] == 75

    def test_results_not_trimmed_when_under_limit(self, clean_state):
        with session_lock:
            session["results"] = [{"batch": i} for i in range(10)]
        snap = _session_snapshot()
        assert len(snap["results"]) == 10

    def test_log_trimmed_to_last_200(self, clean_state):
        with session_lock:
            session["log"] = [f"entry-{i}" for i in range(250)]
        snap = _session_snapshot()
        assert len(snap["log"]) == _MAX_LOG_ENTRIES == 200
        assert snap["log"][0] == "entry-50"
        assert snap["log"][-1] == "entry-249"

    def test_snapshot_is_a_copy_not_a_live_reference(self, clean_state):
        snap = _session_snapshot()
        snap["results"].append({"batch": "mutated"})
        with session_lock:
            assert session["results"] == []


class TestWarnFlagsConsumeOnce:
    def test_warn_batch_dropped_true_then_resets(self, clean_state):
        with session_lock:
            session["warn_batch_dropped"] = True
        first = _session_snapshot()
        assert first["warn_batch_dropped"] is True
        with session_lock:
            assert session["warn_batch_dropped"] is False
        second = _session_snapshot()
        assert second["warn_batch_dropped"] is False

    def test_warn_duration_changed_true_then_resets(self, clean_state):
        with session_lock:
            session["warn_duration_changed"] = True
        first = _session_snapshot()
        assert first["warn_duration_changed"] is True
        with session_lock:
            assert session["warn_duration_changed"] is False
        second = _session_snapshot()
        assert second["warn_duration_changed"] is False

    def test_both_warn_flags_independent(self, clean_state):
        with session_lock:
            session["warn_batch_dropped"] = True
            session["warn_duration_changed"] = False
        snap = _session_snapshot()
        assert snap["warn_batch_dropped"] is True
        assert snap["warn_duration_changed"] is False


class TestResetSession:
    def test_mutates_in_place_same_object_id(self, clean_state):
        session_id_before = id(session)
        _reset_session()
        assert id(session) == session_id_before

    def test_values_restored_to_defaults(self, clean_state):
        with session_lock:
            session["status"] = "recording"
            session["rtsp_url"] = "rtsp://example"
            session["results"] = [{"batch": 1}]
        _reset_session()
        assert session["status"] == _SESSION_DEFAULTS["status"] == "idle"
        assert session["rtsp_url"] == ""
        assert session["results"] == []

    def test_stray_key_not_in_defaults_survives_reset(self, clean_state):
        with session_lock:
            session["is_recording"] = True
        _reset_session()
        assert session["is_recording"] is True

    def test_deep_copy_not_shared_with_defaults_template(self, clean_state):
        _reset_session()
        session["results"].append({"batch": "x"})
        assert _SESSION_DEFAULTS["results"] == []


class TestSlog:
    def test_appends_entry_matching_timestamp_format(self, clean_state):
        _slog("hello world")
        with session_lock:
            log = session["log"]
        assert len(log) == 1
        assert re.match(r"^\[\d{2}:\d{2}:\d{2}\] hello world$", log[0])

    def test_timestamp_matches_current_time_hms(self, clean_state):
        before = time.strftime("%H:%M:%S")
        _slog("x")
        after = time.strftime("%H:%M:%S")
        with session_lock:
            entry = session["log"][-1]
        m = re.match(r"^\[(\d{2}:\d{2}:\d{2})\] x$", entry)
        assert m is not None
        assert before <= m.group(1) <= after

    def test_log_capped_at_max_log_entries(self, clean_state):
        for i in range(_MAX_LOG_ENTRIES + 25):
            _slog(f"msg-{i}")
        with session_lock:
            log = session["log"]
        assert len(log) == _MAX_LOG_ENTRIES
        assert log[-1].endswith(f"msg-{_MAX_LOG_ENTRIES + 24}")

    def test_log_under_cap_not_trimmed(self, clean_state):
        _slog("only one")
        with session_lock:
            log = session["log"]
        assert len(log) == 1
