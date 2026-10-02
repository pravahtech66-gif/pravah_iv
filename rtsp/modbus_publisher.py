import time
import logging

logger = logging.getLogger(__name__)

STATUS_IDLE    = 0
STATUS_RUNNING = 1
STATUS_DONE    = 2
STATUS_ERROR   = 3

_STATUS_NAMES = {
    STATUS_IDLE:    "IDLE",
    STATUS_RUNNING: "RUNNING",
    STATUS_DONE:    "DONE",
    STATUS_ERROR:   "ERROR",
}

_REGISTER_MAP = [
    (0, "40001", "Mean Speed",       "mm/s",  "÷ 1000 → m/s"),
    (1, "40002", "Max Speed",        "mm/s",  "÷ 1000 → m/s"),
    (2, "40003", "Median Speed",     "mm/s",  "÷ 1000 → m/s"),
    (3, "40004", "Status",           "—",     "0=IDLE 1=RUNNING 2=DONE 3=ERROR"),
    (4, "40005", "Timestamp High",   "word",  "high 16 bits of Unix epoch"),
    (5, "40006", "Timestamp Low",    "word",  "low 16 bits of Unix epoch"),
    (6, "40007", "Data Quality",     "%",     "0–100"),
]

_N_REGISTERS = len(_REGISTER_MAP)


def _ms_to_uint16(speed_ms: float) -> int:
    return max(0, min(65535, round(speed_ms * 1000)))


def build_registers(results: dict, quality_pct: int = 100) -> list:
    ts = int(time.time())
    return [
        _ms_to_uint16(results.get("mean_speed",   0.0)),
        _ms_to_uint16(results.get("max_speed",    0.0)),
        _ms_to_uint16(results.get("median_speed", 0.0)),
        STATUS_DONE,
        (ts >> 16) & 0xFFFF,
        ts & 0xFFFF,
        max(0, min(100, int(quality_pct))),
    ]


def print_modbus_registers(results: dict, quality_pct: int = 100) -> None:
    regs = build_registers(results, quality_pct)

    ts_raw = (regs[4] << 16) | regs[5]
    ts_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ts_raw))

    SEP  = "═" * 74
    SEP2 = "─" * 74

    lines = [
        "",
        SEP,
        "  MODBUS REGISTER OUTPUT",
        "  Protocol : Modbus TCP  |  Unit ID : 1  |  Port : 5020",
        "  Function : FC3 — Read Holding Registers  (0-based addr 0–6)",
        SEP2,
        f"  {'SCADA':<8} {'Register Name':<18} {'Raw Value':>10}   {'Decoded':<26} Notes",
        f"  {'Addr':<8} {'':<18} {'(uint16)':>10}   {'':26}",
        SEP2,
    ]

    for (idx, scada_addr, name, unit, note) in _REGISTER_MAP:
        raw = regs[idx]

        if idx in (0, 1, 2):
            decoded = f"{raw / 1000:.4f} m/s"
        elif idx == 3:
            decoded = _STATUS_NAMES.get(raw, f"UNKNOWN({raw})")
        elif idx == 4:
            decoded = f"0x{raw:04X}"
        elif idx == 5:
            decoded = f"0x{raw:04X}  →  {ts_str}"
        elif idx == 6:
            decoded = f"{raw} %"
        else:
            decoded = str(raw)

        lines.append(
            f"  {scada_addr:<8} {name:<18} {raw:>10}   {decoded:<26} {note}"
        )

    lines += [
        SEP2,
        f"  Raw array [HR0..HR6] : {regs}",
        f"  Timestamp decoded    : {ts_str}",
        SEP,
        "",
    ]

    output = "\n".join(lines)
    try:
        print(output)
    except UnicodeEncodeError:
        print(output.encode("ascii", "replace").decode("ascii"))
    logger.info("Modbus register snapshot printed (print-only mode).")
