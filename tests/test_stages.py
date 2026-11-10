import pytest

from yathorlib import STAGES, UnitScale, stage_scale


def test_matches_protocol_pdf_for_z8_stage():
    # Protocol PDF issue 48 p.42 (its factors are rounded, hence rel=1e-6)
    scale = stage_scale("MTS50-Z8")
    assert scale.position == pytest.approx(34554.96)
    assert scale.velocity == pytest.approx(772981.3692, rel=1e-6)
    assert scale.acceleration == pytest.approx(263.8443072, rel=1e-6)


def test_rotary_stage_matches_pdf():
    assert stage_scale("PRM1-Z8").position == pytest.approx(1919.6418578623391, rel=1e-6)
    assert STAGES["PRM1-Z8"]["units"] == "deg"


def test_kmts100em_is_the_mts100m_z8_stage():
    assert stage_scale("KMTS100E/M") == stage_scale("MTS100/M-Z8")
    assert stage_scale("KMTS100E/M").position == pytest.approx(34554.96)


def test_unknown_stage_is_rejected():
    with pytest.raises(KeyError):
        stage_scale("KMTS999")


def test_for_dc_servo_rejects_bad_counts():
    with pytest.raises(ValueError):
        UnitScale.for_dc_servo(0)
