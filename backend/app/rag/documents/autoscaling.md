# Autoscaling Best Practices

Autoscaling lets provisioned capacity track actual demand over time instead of being
fixed at whatever level covers the worst case. Done well, it turns a "pay for peak,
all the time" cost model into a "pay for what you use, when you use it" model. Done
poorly, it either fails to save money (scaling too conservatively) or causes outages
(scaling too slowly or too aggressively).

## When autoscaling helps

Autoscaling delivers the most value when demand is genuinely variable and that
variability is large relative to the cost of running at peak all the time — for
example, daily traffic cycles with a pronounced business-hours peak, weekly patterns
with quiet weekends, or seasonal spikes around specific events. If a workload's demand
is essentially flat, autoscaling adds operational complexity without much savings, and
a simple right-sized fixed allocation is usually the better choice.

## Core design decisions

1. **Choose a demand signal that actually reflects load.** CPU utilization is a common
   default, but it isn't always the right signal — a request-queue-depth or
   requests-per-second signal often reacts faster and more accurately for
   request-driven services, while a memory or connection-count signal may be more
   appropriate for stateful services. Scaling on the wrong signal causes capacity to
   lag or overreact relative to what's actually happening.
2. **Set a minimum floor.** Scaling to zero (or near-zero) capacity saves the most
   money but can introduce cold-start latency that violates a service's latency target
   the moment traffic returns. A sensible minimum keeps enough capacity warm to absorb
   the first wave of a demand increase while the scaler catches up.
3. **Bound the rate of change.** Both scale-up and scale-down should be rate-limited.
   Scaling up too slowly risks a capacity shortfall during a genuine spike; scaling down
   too aggressively risks having to scale back up moments later (with cold-start
   latency) if the drop in demand was brief rather than sustained. A common pattern is
   to scale up faster than you scale down, on the theory that under-provisioning is more
   costly (an incident) than a few extra minutes of over-provisioning (a small amount of
   wasted spend).
4. **Add a cooldown between scaling actions.** Without one, a scaler can oscillate —
   scaling up, then immediately back down, repeatedly — in response to noisy metrics.
   A cooldown period after each scaling action lets the system stabilize before the next
   decision is made.
5. **Validate against both a capacity constraint and a latency constraint.** The
   purpose of autoscaling is to always have enough capacity for current demand, but
   "enough capacity" should be defined in terms of the actual SLA (e.g. p95 latency) the
   workload needs to meet, not just raw throughput. A scaler that satisfies throughput
   but not latency will look successful on a capacity dashboard while still violating
   what users actually experience.

## Forecast-aware autoscaling

Reactive autoscaling (scale based on what's happening right now) always lags demand by
however long it takes to detect the change and provision new capacity. For workloads
with predictable patterns — a known daily peak, a recurring batch job, a weekly
reporting spike — using a demand *forecast* to pre-scale ahead of the expected increase
avoids that lag entirely. This is most valuable when the cost of being late (a latency
spike or outage during the ramp) is high and the pattern is regular enough to forecast
with confidence. It is less valuable, and can actively hurt, when demand is genuinely
unpredictable — pre-scaling for a spike that doesn't materialize is pure waste.

## Common pitfalls

- **Autoscaling database or stateful tiers the same way as stateless compute.**
  Stateful services often have slower, costlier scale-out (data has to move or
  rebalance), so the same aggressive autoscaling policy that works well for a stateless
  web tier can cause thrashing or data-movement overhead on a stateful one.
- **Ignoring startup time.** If a new instance takes several minutes to become useful
  (boot, warm caches, join a cluster), scaling decisions need to account for that lag —
  otherwise the scaler is always reacting to demand that has already passed.
- **No upper bound.** An unbounded scale-up policy turns a traffic spike (or a bug that
  looks like one) into a runaway bill. A maximum capacity ceiling, even a generous one,
  is cheap insurance.
