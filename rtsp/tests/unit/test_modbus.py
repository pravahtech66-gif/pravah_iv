import re

import pytest

from modbus_publisher import (
    STATUS_DONE,
    _ms_to_uint16,
    build_registers,
    print_modbus_registers,
)


class TestMsToUint16:
    def test_typical_speed_scales_by_1000_and_rounds(self):
        assert _ms_to_uint16(1.847) == 1847

    def test_rounds_to_nearest_integer(self):
        assert _ms_to_uint16(1.8474) == 1847
        assert _ms_to_uint16(1.8476) == 1848

    def test_zero_speed(self):
        assert _ms_to_uint16(0.0) == 0

    def test_negative_speed_clamps_to_zero(self):
        assert _ms_to_uint16(-5.0) == 0

    def test_clamps_at_65535_for_out_of_range_speed(self):
        assert _ms_to_uint16(65.535) == 65535

    def test_clamps_above_max_encodable_speed(self):
        assert _ms_to_uint16(9999.0) == 65535

    def test_value_just_under_max_is_not_clamped(self):
        assert _ms_to_uint16(65.0) == 65000


class TestBuildRegisters:
    def test_returns_seven_registers(self):
        regs = build_registers({"mean_speed": 1.0, "max_speed": 2.0, "median_speed": 1.5})
        assert len(regs) == 7

    def test_speed_fields_scaled_into_hr0_hr2(self):
        regs = build_registers({
            "mean_speed": 1.847, "max_speed": 2.310, "median_speed": 1.900,
        })
        assert regs[0] == 1847
        assert regs[1] == 2310
        assert regs[2] == 1900

    def test_missing_speed_keys_default_to_zero(self):
        regs = build_registers({})
        assert regs[0] == 0
        assert regs[1] == 0
        assert regs[2] == 0

    def test_status_register_is_always_status_done(self):
        regs = build_registers({"mean_speed": 0.0, "max_speed": 0.0, "median_speed": 0.0})
        assert regs[3] == STATUS_DONE == 2

    def test_timestamp_registers_reconstruct_to_a_recent_epoch(self):
        import time
        before = int(time.time())
        regs = build_registers({"mean_speed": 0.0, "max_speed": 0.0, "median_speed": 0.0})
        after = int(time.time())
        ts = (regs[4] << 16) | regs[5]
        assert before <= ts <= after

    def test_quality_pct_default_is_100(self):
        regs = build_registers({"mean_speed": 0.0, "max_speed": 0.0, "median_speed": 0.0})
        assert regs[6] == 100

    def test_quality_pct_passed_through_when_in_range(self):
        regs = build_registers({"mean_speed": 0.0, "max_speed": 0.0, "median_speed": 0.0},
                                quality_pct=42)
        assert regs[6] == 42

    def test_quality_pct_clamps_above_100(self):
        regs = build_registers({"mean_speed": 0.0, "max_speed": 0.0, "median_speed": 0.0},
                                quality_pct=150)
        assert regs[6] == 100

    def test_quality_pct_clamps_below_zero(self):
        regs = build_registers({"mean_speed": 0.0, "max_speed": 0.0, "median_speed": 0.0},
                                quality_pct=-10)
        assert regs[6] == 0

    def test_negative_speed_in_results_clamps_to_zero_register(self):
        regs = build_registers({"mean_speed": -3.0, "max_speed": 0.0, "median_speed": 0.0})
        assert regs[0] == 0

    def test_none_speed_value_raises_typeerror(self):
        with pytest.raises(TypeError):
            build_registers({"mean_speed": None, "max_speed": 0.0, "median_speed": 0.0})


class TestPrintModbusRegisters:
    def test_prints_formatted_speed_lines(self, capsys):
        print_modbus_registers({
            "mean_speed": 1.847, "max_speed": 2.310, "median_speed": 1.900,
        })
        out = capsys.readouterr().out
        assert "1.8470 m/s" in out
        assert "2.3100 m/s" in out
        assert "1.9000 m/s" in out

    def test_prints_raw_register_values(self, capsys):
        print_modbus_registers({
            "mean_speed": 1.847, "max_speed": 2.310, "median_speed": 1.900,
        })
        out = capsys.readouterr().out
        assert "1847" in out
        assert "2310" in out
        assert "1900" in out

    def test_prints_status_name_done(self, capsys):
        print_modbus_registers({"mean_speed": 0.0, "max_speed": 0.0, "median_speed": 0.0})
        out = capsys.readouterr().out
        assert "DONE" in out

    def test_prints_quality_percent_suffix(self, capsys):
        print_modbus_registers(
            {"mean_speed": 0.0, "max_speed": 0.0, "median_speed": 0.0},
            quality_pct=77,
        )
        out = capsys.readouterr().out
        assert "77 %" in out

    def test_prints_raw_array_line_matching_build_registers(self, capsys):
        results = {"mean_speed": 1.0, "max_speed": 2.0, "median_speed": 3.0}
        regs = build_registers(results, quality_pct=90)
        print_modbus_registers(results, quality_pct=90)
        out = capsys.readouterr().out
        m = re.search(r"Raw array \[HR0\.\.HR6\] : \[(.*?)\]", out)
        assert m is not None
        printed = [int(x.strip()) for x in m.group(1).split(",")]
        assert printed[0:4] == regs[0:4]
        assert printed[6] == regs[6]

    def test_prints_hex_timestamp_words(self, capsys):
        print_modbus_registers({"mean_speed": 0.0, "max_speed": 0.0, "median_speed": 0.0})
        out = capsys.readouterr().out
        assert re.search(r"0x[0-9A-F]{4}", out)

    def test_returns_none(self):
        result = print_modbus_registers(
            {"mean_speed": 0.0, "max_speed": 0.0, "median_speed": 0.0}
        )
        assert result is None


class TestPrintSurvivesNonUnicodeStdout:
    def test_print_falls_back_to_ascii_when_stdout_cannot_encode(self, monkeypatch):
        import io
        import sys

        class AsciiOnlyStdout(io.TextIOBase):
            def __init__(self):
                self.chunks = []

            def write(self, s):
                s.encode("ascii")
                self.chunks.append(s)
                return len(s)

        fake = AsciiOnlyStdout()
        monkeypatch.setattr(sys, "stdout", fake)

        print_modbus_registers({"mean_speed": 1.0, "max_speed": 2.0, "median_speed": 1.5})

        text = "".join(fake.chunks)
        assert "Mean Speed" in text
        assert "1000" in text
        assert "═" not in text and "→" not in text
