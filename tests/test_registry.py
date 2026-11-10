from orbit.schema import (
    SIGNALS,
    ConcernDirection,
    SignalCategory,
    SignalKind,
    SignalType,
    Source,
    get_spec,
    signals_in,
)


def test_every_signal_type_has_a_spec():
    assert set(SIGNALS) == set(SignalType)


def test_specs_are_consistent():
    for signal, spec in SIGNALS.items():
        assert spec.signal is signal
        assert spec.plausible_min < spec.plausible_max
        assert spec.unit.isascii(), "canonical units must be ASCII so files stay portable"
        assert spec.allowed_sources, f"{signal} has no allowed source"
        if spec.kind is SignalKind.ORDINAL:
            assert spec.scale_labels is not None
            assert len(spec.scale_labels) == spec.plausible_max - spec.plausible_min + 1


def test_lookup_by_string():
    assert get_spec("skin_temp").unit == "degC"
    assert get_spec(SignalType.HRV_RMSSD).concern is ConcernDirection.DOWN


def test_scale_labels():
    assert get_spec("symptom_fatigue").scale_label(2) == "moderate"
    assert get_spec("mood").scale_label(1) == "very low"
    assert get_spec("skin_temp").scale_label(34.5) is None


def test_symptoms_only_come_from_checkin():
    for spec in signals_in(SignalCategory.SYMPTOM):
        assert spec.allowed_sources == frozenset({Source.CHECKIN})
