def _log(job_state, msg):
    job_state.setdefault("log", [])
    job_state["log"].append(str(msg))
