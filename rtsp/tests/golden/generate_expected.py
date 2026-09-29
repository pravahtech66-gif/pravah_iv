import json
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))

from test_pipeline_golden import (DISCRETE_KEYS, EXPECTED_PATH, NUMERIC_KEYS,
                                  VIDEO_PATH, run_golden)


def main():
    if not VIDEO_PATH.exists():
        sys.exit(f"fixture video not found: {VIDEO_PATH}")
    with tempfile.TemporaryDirectory() as out:
        summary, _ = run_golden(out)
    expected = {k: summary[k] for k in DISCRETE_KEYS + NUMERIC_KEYS}
    EXPECTED_PATH.write_text(json.dumps(expected, indent=2))
    print("wrote", EXPECTED_PATH)
    print(json.dumps(expected, indent=2))


if __name__ == "__main__":
    main()
