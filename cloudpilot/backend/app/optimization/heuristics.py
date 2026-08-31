"""Documented, deterministic latency/availability heuristics.

These are explicit simplifying models — not measured telemetry, not ML,
not an LLM guess:

- **Latency** follows a queueing-theory-style blow-up as utilization
  approaches capacity: `latency = base_latency / (1 - utilization)`,
  utilization capped below 1 to avoid a division blow-up. This is the
  standard qualitative shape of latency-under-load (M/M/1-like); it is not
  a calibrated queueing model.
- **Availability** follows an independent-failure redundancy model: with
  `N` instances each unavailable independently with probability
  `base_failure_rate`, the whole fleet is down only if *all* of them are
  down simultaneously: `availability = 1 - base_failure_rate ** N`.

Both heuristics are also invertible (`min_capacity_for_latency`,
`min_instances_for_availability`), which lets the optimizer fold latency
and availability targets into linear capacity/count lower bounds *before*
solving, rather than needing a nonlinear constraint inside OR-Tools.
"""

from __future__ import annotations

import math

MAX_UTILIZATION = 0.99


def estimate_latency_ms(base_latency_ms: float, demand: float, capacity: float) -> float:
    if capacity <= 0:
        return float("inf")
    utilization = min(demand / capacity, MAX_UTILIZATION)
    return base_latency_ms / (1 - utilization)


def estimate_availability(base_failure_rate: float, instance_count: int) -> float:
    n = max(instance_count, 1)
    return 1.0 - (base_failure_rate**n)


def min_capacity_for_latency(demand: float, base_latency_ms: float, max_latency_ms: float) -> float:
    """Smallest capacity such that estimate_latency_ms(...) <= max_latency_ms.

    If even a near-idle instance of this tier can't meet `max_latency_ms`,
    no finite capacity satisfies the target under this model — return a
    very large number so the caller ends up provisioning heavily and the
    resulting scenario still gets flagged as a latency violation by
    `check_constraints`, rather than the request silently succeeding.
    """
    if max_latency_ms <= base_latency_ms:
        return demand * 1000.0

    max_allowed_utilization = min(1 - (base_latency_ms / max_latency_ms), MAX_UTILIZATION)
    if max_allowed_utilization <= 0:
        return demand * 1000.0

    return demand / max_allowed_utilization


def min_instances_for_availability(base_failure_rate: float, min_availability: float) -> int:
    """Smallest N such that estimate_availability(...) >= min_availability."""
    if min_availability <= 0 or base_failure_rate <= 0:
        return 1
    if min_availability >= 1.0:
        return 20  # asymptotic target; cap the fleet at a bounded size

    # 1 - f^n >= a  =>  f^n <= 1-a  =>  n >= log(1-a)/log(f)  (log(f) < 0)
    required = math.log(1 - min_availability) / math.log(base_failure_rate)
    return max(1, math.ceil(required))
