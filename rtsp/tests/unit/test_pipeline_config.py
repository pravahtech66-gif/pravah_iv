from piv.pipeline import resolve_h_ref


def test_nested_gcps_h_ref_is_used():
    cfg = {"gcps": {"h_ref": 0.3}}
    assert resolve_h_ref(cfg, h_a=0.8) == 0.3


def test_top_level_h_ref_wins_over_nested():
    cfg = {"h_ref": 0.1, "gcps": {"h_ref": 0.3}}
    assert resolve_h_ref(cfg, h_a=0.8) == 0.1


def test_falls_back_to_h_a_when_neither_present():
    cfg = {"gcps": {"src": [], "dst": []}}
    assert resolve_h_ref(cfg, h_a=0.8) == 0.8


def test_explicit_null_is_treated_as_absent():
    cfg = {"h_ref": None, "gcps": {"h_ref": None}}
    assert resolve_h_ref(cfg, h_a=0.8) == 0.8
