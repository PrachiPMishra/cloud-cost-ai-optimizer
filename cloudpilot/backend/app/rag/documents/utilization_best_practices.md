# Utilization Monitoring Best Practices

Every other cost optimization technique — right-sizing, autoscaling, choosing a
commitment term, tiering storage — depends on having a trustworthy picture of how a
resource is actually being used. Utilization monitoring is the foundation the other
decisions are built on, not a separate, optional practice.

## What to measure

- **The metric that actually constrains the resource**, not just the easiest one to
  collect. CPU utilization is the most commonly available signal, but for a given
  workload the real bottleneck might be memory, I/O throughput, network bandwidth, or
  connection count. Optimizing against the wrong metric can look successful on a
  dashboard while missing the actual constraint entirely.
- **Distribution, not just an average.** An average utilization figure hides both idle
  periods and spikes. A resource averaging 30% utilization could be steady at 30% all
  day, or idle most of the day with short spikes to 100% — these call for completely
  different decisions (the first is a right-sizing candidate, the second may need
  autoscaling or a latency-aware capacity floor instead).
- **Trend over a meaningful window.** A single day, especially an atypical one (a
  holiday, an incident, a one-off batch job), is not representative. Two to four weeks
  of trailing data, covering at least one full weekly cycle, is a more reliable basis
  for a sizing or commitment decision.

## Target utilization bands

There is no universally correct target utilization — it depends on how quickly the
resource can be scaled and how costly a shortfall would be — but a few general
patterns are widely useful starting points:

- Resources that scale slowly (large stateful databases, resources with long boot
  times) generally want a lower target utilization with more headroom, since there's
  little ability to react quickly if demand exceeds the plan.
- Resources that scale quickly (stateless compute behind an autoscaler) can safely run
  at a higher target utilization, since additional capacity can be added before
  latency degrades meaningfully.
- Running consistently very low (workloads idling most of the time with no plan to use
  that capacity) is close to pure waste and a strong right-sizing or scale-to-zero
  candidate.
- Running consistently very high, with no headroom for normal variability, is a
  reliability risk more than a cost-efficiency win — it usually means the next
  unexpected spike in demand will cause a latency or availability incident.

The right target sits between those two extremes, calibrated to how fast capacity can
respond and how much a shortfall would cost versus how much the idle headroom costs.

## Turning monitoring into action

Utilization data only pays for itself if someone actually acts on it. A few practices
make that more likely:

1. **Surface utilization next to cost, not in a separate dashboard.** A chronically
   idle resource is far more likely to get attention when its utilization and its
   dollar cost are shown together.
2. **Review regularly, not only during an incident or a budget review.** Utilization
   drifts continuously; a resource that was correctly sized six months ago may no
   longer be, and nothing about that drift is likely to trigger an alert on its own.
3. **Treat persistent low utilization as a decision to make, not just a fact to note.**
   The options are usually: right-size down, consolidate with another workload,
   autoscale it, or decommission it if it's no longer needed — but someone has to
   actually choose one.
4. **Be skeptical of utilization data collected during an atypical period.** A resource
   monitored only during a quiet stretch will look over-provisioned; monitored only
   during a promotional spike, it will look correctly sized or even under-provisioned.
   Utilization-driven decisions are only as good as the representativeness of the
   window they're based on.
