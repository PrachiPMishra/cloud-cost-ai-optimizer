# Storage Optimization

Storage costs are easy to ignore because, unlike a CPU-bound compute instance, storage
doesn't visibly "run slow" when it's oversized or on the wrong tier — the bill simply
grows quietly in the background. Left unmanaged, storage cost tends to increase
indefinitely, because data is created continuously but is only deleted or
demoted deliberately.

## Storage tiers exist for a reason

Cloud storage services typically offer multiple tiers that trade retrieval latency and
availability characteristics for a lower per-gigabyte price:

- **Standard / hot tier** — lowest latency, highest cost per gigabyte, meant for data
  accessed frequently or served directly to users.
- **Infrequent-access / cool tier** — a meaningfully lower price per gigabyte in
  exchange for higher retrieval latency and, often, a small per-retrieval fee. Meant for
  data that is kept for a while but rarely read — backups, older logs, historical
  snapshots.
- **Archive / cold tier** — the lowest price per gigabyte, with retrieval times measured
  in minutes to hours rather than milliseconds. Meant for data kept for compliance or
  long-term retention that is essentially never read.

Moving eligible data down a tier is often the single largest storage cost lever
available, precisely because most stored data is written once and read rarely, if
ever, after the first short window.

## How to decide what belongs on which tier

1. **Look at actual access patterns, not assumptions about them.** "We might need this
   quickly" is a common justification for keeping everything on the hot tier, but it's
   worth checking whether that data has actually been read in the last 30–90 days
   before accepting the higher cost as necessary.
2. **Match the tier's retrieval latency to the real requirement.** If a consumer of the
   data can tolerate seconds-to-minutes of retrieval latency, an infrequent-access tier
   is very likely a free cost reduction with no practical downside. If a consumer needs
   millisecond access, moving that data off the hot tier will cause real problems — the
   decision has to be driven by the actual read path, not just cost.
3. **Consider a lifecycle policy instead of one-off tier decisions.** Data usually gets
   colder as it ages — a log file is read constantly the day it's written and almost
   never again a month later. An automated lifecycle rule (e.g. "move to
   infrequent-access after 30 days, archive after 180") captures this pattern without
   requiring a manual decision for every object.
4. **Don't forget the retrieval and request-side costs.** Cheaper tiers often charge
   more per request or per retrieval; if the actual access pattern involves frequent
   small reads even for "cold" data, a naive move to a cheaper tier can backfire on the
   request-cost side even as the storage-cost side improves. The right comparison is
   total cost under the real access pattern, not the headline per-gigabyte price alone.

## Beyond tiering

- **Delete what nobody needs.** Retention policies, expired temporary data, and
  duplicate copies are common and easy to overlook. Tiering reduces the cost of keeping
  data around; deletion eliminates it entirely, and is always cheaper than any tier.
- **Compress and deduplicate where practical.** For data types that compress well (text
  logs, some database exports), storage footprint — and therefore cost — can shrink
  substantially before any tiering decision is even made.
- **Watch network/egress costs alongside storage costs.** Moving data between tiers,
  regions, or out to the internet often carries its own cost that can dominate the
  storage savings if not accounted for up front.

## Common pitfalls

- **Tiering data that's still actively read**, causing a latency regression that
  outweighs the savings.
- **Treating tiering as a one-time migration** rather than an ongoing lifecycle policy,
  so newly created data accumulates on the expensive tier again within months.
- **Optimizing storage cost while ignoring the availability guarantees of each tier** —
  cheaper tiers sometimes carry a slightly lower availability SLA, which matters for
  data with a hard availability requirement.
