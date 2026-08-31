"""Currency conversion — a presentation-layer concern only.

Every persisted and computed monetary value in this system is USD, always:
`pricing` rates, `forecasts`/`cost_predictions` amounts, `optimization_runs`/
`scenarios` costs, and every number an agent tool returns or logs to
`agent_events`. This module exists solely so the API can tell the frontend
the current USD->INR rate; the frontend uses it to reformat already-fetched
USD figures for display, client-side, without a backend round-trip (see
`GET /api/settings`'s `usd_to_inr_rate` field and the frontend's currency
toggle).

This module must never be imported by `app.forecasting`, `app.pricing`,
`app.optimization`, `app.agents`, or `app.tools` — those layers compute and
persist USD only. `tests/test_currency_boundary.py` enforces this by
scanning those packages' source for any reference to this module.

**Design choice — a single configurable rate, not a versioned rates table:**
pricing data uses a versioned table (`pricing.effective_date`) because a
specific historical rate can change what a specific historical bill *should
have cost* — that's a real calculation with a right answer. Display currency
conversion has no such requirement: nothing is ever computed in INR, so
there is no notion of "what rate was in effect when this number was
computed" to preserve. Only the *current* rate is ever needed, which is why
a single `USD_TO_INR_RATE` env var (`app/config/settings.py`) is enough —
changing it takes effect for every subsequent read, with no migration or
backfill implications, because it never touches persisted data.
"""

from __future__ import annotations

from app.config import get_settings

DEFAULT_USD_TO_INR_RATE = 83.0


def get_usd_to_inr_rate() -> float:
    """The current display-only USD->INR rate, from `USD_TO_INR_RATE` (env
    var / `.env`) via `app.config.get_settings()`."""
    return get_settings().usd_to_inr_rate


def usd_to_inr(usd_amount: float, rate: float | None = None) -> float:
    """Convert an already-computed USD amount to INR for display.

    Never call this before a calculation, and never persist its result —
    it exists only to format a number that's about to be shown to a user.
    """
    return usd_amount * (rate if rate is not None else get_usd_to_inr_rate())
