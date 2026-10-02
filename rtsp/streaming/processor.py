import copy
import hashlib
import json
import shutil
import threading
import time

from streaming.config import GCP_REFERENCE_PATH
from streaming.session import session, session_lock, _slog
from streaming.clip_queue import take_oldest_clip
from streaming.clip_integrity import check_clip_integrity
from streaming.clip_fitness import assess_clip_fitness
from streaming.clip_manifest import write_clip_manifest
from streaming.video_files import _cleanup_file
from piv import run_pipeline


def _assess_fitness_or_none(clip_path, config):
    reference = GCP_REFERENCE_PATH if GCP_REFERENCE_PATH.exists() else None
    try:
        return assess_clip_fitness(clip_path, config, reference)
    except Exception as e:
        _slog(f"Fitness check unavailable ({type(e).__name__}) — running PIV without it")
        return None


def _processor_thread(stop_event: threading.Event, batch_ready_event: threading.Event) -> None:
    while not stop_event.is_set():
        queued = take_oldest_clip()
        if queued is None:
            batch_ready_event.wait(timeout=1.0)
            batch_ready_event.clear()
            continue
        batch_path, batch_idx = queued

        with session_lock:
            output_dir = session["_output_dir"]
            config = copy.deepcopy(session["_pipeline_config"]) if session["_pipeline_config"] else None
            audit_dir = session["_audit_dir"]
            rtsp_url = session["rtsp_url"]
            duration_s = session["batch_duration_s"]
            session["batch_index_processing"] = batch_idx

        _slog(f"Processor woke up — batch={batch_idx}, path={batch_path.name}, config={'present' if config else 'MISSING'}")

        try:
            if config is None:
                continue

            integrity = check_clip_integrity(batch_path, duration_s)
            if not integrity.passed:
                _slog(f"Batch {batch_idx}: REJECTED before PIV — {'; '.join(integrity.reasons)}")
                if audit_dir:
                    nc_dir = audit_dir / "not_considered"
                    nc_dir.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(batch_path), str(nc_dir / batch_path.name))
                    _slog(f"[audit] Rejected batch saved → not_considered/{batch_path.name}")
                continue

            fitness = _assess_fitness_or_none(batch_path, config)
            fitness_fields = {
                "fitness_score": fitness.score if fitness else None,
                "fitness_status": fitness.status if fitness else None,
                "fitness_reasons": fitness.reasons if fitness else None,
            }

            if fitness and fitness.status == "invalid":
                result = {
                    "batch": batch_idx,
                    "ts": time.time(),
                    "mean_speed": None,
                    "median_speed": None,
                    "max_speed": None,
                    "vector_mean_speed": None,
                    "vector_median_speed": None,
                    **fitness_fields,
                }
                with session_lock:
                    session["results"].append(result)
                _slog(f"Batch {batch_idx}: camera moved — recalibrate GCPs "
                      f"({'; '.join(fitness.reasons)}) — PIV skipped")
            else:
                _slog(f"Batch {batch_idx}: processing {batch_path.name}")
                cfg_sha1 = hashlib.sha1(
                    json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()[:10]
                cfg_keys = {k: config.get(k) for k in (
                    "framestep", "frames", "use_stabilization", "use_fixed_intrinsics",
                    "h_a", "h_ref", "lens_position")}
                _slog(f"Batch {batch_idx}: config sha1={cfg_sha1} {cfg_keys}")
                job_state = {"log": session["log"], "cancel": False}
                job_id = f"stream_b{batch_idx}"

                with session_lock:
                    _timeout = max(120, session["batch_duration_s"] * 5)
                _result_box = [None, None]

                def _run_pipeline():
                    try:
                        _result_box[0] = run_pipeline(config, str(batch_path), job_state, job_id, str(output_dir))
                    except Exception as exc:
                        _result_box[1] = exc

                worker = threading.Thread(target=_run_pipeline, daemon=True)
                worker.start()
                worker.join(timeout=_timeout)

                if worker.is_alive():
                    _slog(f"Batch {batch_idx}: pipeline TIMED OUT after {_timeout}s — skipping")
                    job_state["cancel"] = True
                elif _result_box[1] is not None:
                    raise _result_box[1]
                else:
                    summary = _result_box[0]
                    result = {
                        "batch": batch_idx,
                        "ts": time.time(),
                        "mean_speed": summary.get("mean_speed"),
                        "median_speed": summary.get("median_speed"),
                        "max_speed": summary.get("max_speed"),
                        "vector_mean_speed": None,
                        "vector_median_speed": None,
                        **fitness_fields,
                    }
                    with session_lock:
                        session["results"].append(result)
                    _slog(f"Batch {batch_idx}: done — mean {result['mean_speed']} m/s")

            audit_mp4 = audit_dir / f"vid_{batch_idx + 1}.mp4" if audit_dir else None
            if audit_mp4 is not None and audit_mp4.exists():
                write_clip_manifest(audit_mp4, source="lspiv_batch", rtsp_url=rtsp_url,
                                    requested_duration_s=duration_s, integrity=integrity,
                                    fitness=fitness, water_level_m=config.get("h_a"))

        except Exception as e:
            _slog(f"Batch {batch_idx}: pipeline error — {e}")
        finally:
            _cleanup_file(batch_path)
            with session_lock:
                session["batch_index_processing"] = None

    _slog("Processor thread exiting")
