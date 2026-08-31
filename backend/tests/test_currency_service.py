from app.config import get_settings
from app.services.currency import DEFAULT_USD_TO_INR_RATE, get_usd_to_inr_rate, usd_to_inr


def test_usd_to_inr_uses_explicit_rate_when_given() -> None:
    assert usd_to_inr(10.0, rate=80.0) == 800.0
    assert usd_to_inr(0.0, rate=80.0) == 0.0
    assert usd_to_inr(-5.0, rate=80.0) == -400.0


def test_usd_to_inr_falls_back_to_configured_rate() -> None:
    configured_rate = get_settings().usd_to_inr_rate
    assert usd_to_inr(100.0) == 100.0 * configured_rate


def test_get_usd_to_inr_rate_matches_settings() -> None:
    assert get_usd_to_inr_rate() == get_settings().usd_to_inr_rate


def test_default_rate_constant_is_a_positive_number() -> None:
    # Not asserted equal to the configured rate (that's env-overridable) —
    # just documents that the shipped default is a sane, positive value.
    assert DEFAULT_USD_TO_INR_RATE > 0
