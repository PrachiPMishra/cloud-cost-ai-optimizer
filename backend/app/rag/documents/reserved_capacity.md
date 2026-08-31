# Reserved Capacity and Commitment-Based Pricing

Most cloud providers offer a discount in exchange for committing to use (and pay for)
a resource for a fixed term — commonly one year or three years — instead of paying the
on-demand rate hour by hour. The trade is straightforward: give up some flexibility,
get a lower price. The discount is usually larger for longer commitment terms, since
the provider is trading its own capacity-planning certainty for the commitment.

## When a commitment makes sense

Reserved or committed pricing is a good fit for a workload with a **stable, predictable
baseline** — capacity that is going to be running regardless of what else changes,
because it corresponds to a steady-state need rather than a temporary or highly
variable one. The classic sign that a workload is a good commitment candidate is that
its utilization has stayed within a narrow band for a meaningful stretch of time (weeks
to months) with no planned changes on the horizon.

Reserved pricing is a poor fit for:

- **Workloads still being right-sized.** Committing to a specific size before
  right-sizing is finished locks in whatever size was guessed at commitment time,
  even if it turns out to be wrong.
- **Highly variable or bursty workloads**, where a large share of capacity is only
  needed some of the time — committing to peak capacity wastes the discount on hours
  that would otherwise have been unnecessary anyway, and committing to average capacity
  under-provisions the peaks.
- **Workloads with a known short lifespan** — a project ending in three months has no
  business committing to a one-year term, no matter how attractive the discount rate
  looks in isolation.
- **Anything in an architecture that's expected to change materially** — if a service is
  being migrated, replaced, or re-platformed within the commitment window, the
  commitment can easily outlive the resource it was meant to cover.

## Choosing a term length

Longer terms carry a larger discount but a larger commitment risk. A reasonable
approach is to size the *term* to match the confidence horizon of the workload:
commit for as long as you're genuinely confident the baseline will hold, and no longer.
A one-year commitment on a stable, well-understood baseline is usually a safe,
high-value decision; a three-year commitment is best reserved for workloads with a
long, well-established track record and no anticipated architectural change.

## Combining commitments with right-sizing and autoscaling

Committed capacity works best as the **floor**, not the entirety, of a resource's
footprint: commit to the stable baseline that's reliably needed around the clock, and
let autoscaling (or plain on-demand capacity) handle the variable portion above that
floor. This captures the discount on the part of the workload that's genuinely
predictable while retaining flexibility for the part that isn't. Committing to 100% of
a workload's peak capacity, rather than its baseline, gives up that flexibility for no
additional benefit — the peak-only hours would have cost the on-demand rate either way.

Right-sizing should generally happen *before* committing, not after — committing to an
oversized resource just locks in the waste at a discount instead of removing it.

## Common pitfalls

- **Committing to the current size without checking whether it's already right-sized.**
- **Choosing the longest available term purely because it has the best headline
  discount**, without weighing the risk of the workload changing during that window.
- **Committing 100% of peak capacity** instead of leaving room for on-demand or
  autoscaled capacity to absorb genuine variability.
- **Forgetting to revisit commitments when a term ends** — an expired or soon-to-expire
  commitment reverting silently to on-demand pricing is a common source of unexpected
  cost increases.
