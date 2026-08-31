# Right-Sizing Cloud Resources

Right-sizing is the practice of matching the capacity of a provisioned resource — an
instance type, a database tier, a memory allocation — to the workload it actually
serves, instead of the workload it might theoretically need to serve at some unlikely
peak. It is usually the single highest-leverage cost lever available, because
over-provisioning compounds silently: a resource sized 2x larger than necessary costs
roughly 2x more for every hour it runs, whether or not anyone notices.

## Why over-provisioning happens

Teams tend to over-provision for a few predictable reasons:

- **Launch-time guessing.** A resource is sized once, at launch, based on a rough
  estimate of peak load, and is never revisited once traffic patterns stabilize.
- **Safety margin stacking.** Each team in a chain (application owner, platform team,
  on-call engineer) independently adds their own margin "just in case," and the margins
  compound.
- **Fear of a repeat incident.** After a capacity-related outage, the reflex is to
  over-provision broadly rather than fix the specific bottleneck that caused it.
- **Lack of visibility.** Utilization metrics exist but nobody is looking at them
  against cost, so a chronically idle resource never surfaces as a problem.

## How to right-size correctly

1. **Look at trailing utilization, not a single snapshot.** A resource's CPU/memory
   utilization over the last 2–4 weeks, including its actual peaks, is a far better
   sizing signal than a guess. Right-sizing decisions made from a single busy afternoon
   tend to over-provision; decisions made from a single quiet Sunday tend to
   under-provision.
2. **Size to the peak you actually need to survive, not an arbitrary multiple of
   average load.** If peak utilization comfortably fits within a smaller tier with
   headroom to spare, the larger tier is very likely pure waste.
3. **Account for latency, not just throughput.** A smaller instance can often handle
   the same request volume as a larger one, but with higher per-request latency because
   there's less spare capacity to absorb bursts. Right-sizing should be checked against
   a latency target, not capacity alone — the cheapest instance that satisfies capacity
   is not automatically the right choice if it pushes latency past what the workload
   requires.
4. **Re-evaluate periodically, not once.** Workloads drift. A resource sized correctly
   six months ago may now be significantly over- or under-provisioned as usage patterns
   change. Right-sizing is a recurring practice, not a one-time project.
5. **Prefer a small number of well-understood tiers over many bespoke sizes.** Fewer,
   well-tested instance sizes are easier to right-size accurately and easier to reason
   about during incidents than a large sprawl of custom configurations.

## Common pitfalls

- **Right-sizing against average utilization alone.** Average utilization hides bursts;
  a resource that averages 20% utilization but spikes to 95% during a daily batch job
  is not a good right-sizing candidate without also addressing the spike.
- **Ignoring the cost of downsizing mistakes.** If a workload is latency-sensitive,
  downsizing too aggressively can turn a cost win into a reliability incident. The right
  target is the smallest resource that still meets the latency and availability bar —
  not simply the smallest resource that survives on average.
- **Treating right-sizing as purely a compute problem.** The same principle applies to
  attached storage, allocated memory, and even network bandwidth reservations — any
  dimension that's provisioned ahead of actual demand is a right-sizing candidate.

## When right-sizing alone isn't enough

If utilization varies significantly over time (daily or weekly cycles, seasonal spikes),
a single fixed "right size" will always be a compromise between the busy and quiet
periods. In that situation, right-sizing should be paired with autoscaling (see the
autoscaling guide) so that capacity tracks demand directly instead of being pinned to
one size that's only correct some of the time.
