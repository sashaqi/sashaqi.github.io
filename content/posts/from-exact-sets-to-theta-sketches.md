---
title: From Exact Sets to Theta Sketches
date: '2026-01-31'
draft: false
tags:
- machine-learning
- ads
- Distributed Systems
- Data Engineering
categories:
- Technology
author:
- Sasha Qi
aliases:
- /posts/from-exact-sets-to-sketches/
---

## 1. An Audience Builder That Won't Stop Spinning

### 1.1 The scene

A product manager sends a query to an audience builder: *installed the app in the last 30 days*. The UI spins for 12 seconds and returns "estimated reach: 4.7M."

He adds a second condition: *and purchased product A*. Another 15 seconds.

He adds a third — an exclusion: *but did not purchase product B*. This one runs for 40 seconds and times out.

He comes to ask: why does each additional condition make it slower? Can we make this instant?

The request sounds simple. Behind it sits one of the most expensive classes of operation in distributed systems: large-scale distinct counting, and its harder variant — distinct counting under arbitrary set operations.

The root cause is that deduplication is inherently incompressible. Summing order revenue needs one accumulator and constant memory. Counting distinct purchasers requires remembering every user ID you have ever seen; otherwise you cannot tell whether the next ID is new. One billion users at 64 bits per hash is 8 GB — for a single metric on a single dimension combination. Every condition the product manager adds is another deduplicating shuffle across billions of rows.

### 1.2 This product actually exists: AppsFlyer Audiences Segmentation

The scene above is not hypothetical. AppsFlyer's Audiences Segmentation product does exactly this: advertisers define an audience by dragging conditions in a UI, the system returns an estimated size in real time, and once the number looks right the audience is materialized into an actual targeting list (Cohen, 2020).

The scale: roughly 100 billion events ingested per day.

Three constraints, all typical:

- **Latency.** Every click in the UI must update the number in under a second, or the interaction breaks down.
- **Accuracy.** The number has to be good enough to act on — advertisers set budgets against it.
- **Multi-tenancy and open schema.** Customers can send arbitrary custom event names and event attributes (`product_type=shirt`, `level_number=3`). The platform does not know in advance what dimensions will exist.

A concrete query looks like this: *how many distinct users installed the app in the last month, purchased products A and B, but did not purchase product C?*

Translated into data-structure terms, this is a tree. Leaves are atomic conditions, each corresponding to a set of user IDs. Internal nodes are unions, intersections, and differences. Answering "how many" means evaluating those set operations bottom-up and then counting distinct one more time.

![AppsFlyer audience builder and its corresponding tree structure](https://d2908q01vomqb2.cloudfront.net/b6692ea5df920cad691c20319a6fffd7a4a766b8/2024/08/01/BDB-3551-1-1.png)

*Figure 1: Conditions defined in the UI and the set-operation tree they translate into. Source: Pelts et al., 2024*

Those two words — *set operations* — are the dividing line for everything that follows.

### 1.3 Why HyperLogLog isn't enough

Anyone who has done large-scale distinct counting knows HyperLogLog (HLL). Introduced by Flajolet et al. (2007), it has been the default answer in this space for two decades.

The idea: hash each element into a bit string and look at how many consecutive zeros it starts with. If you see a string starting with 20 zeros among a pile of random bit strings, you have probably seen about 2²⁰ distinct elements, because that pattern occurs with probability 2⁻²⁰. HLL distributes elements across many buckets, stores only the longest run of leading zeros seen per bucket, and takes a harmonic mean at the end.

The design is remarkably cheap. Each bucket needs only a few bits, so an HLL with 2¹⁴ buckets fits in 16 KB and estimates cardinalities in the hundreds of millions to within about 1%.

But HLL has a structural limit: it only supports union. Merging two HLLs is natural — take the per-bucket maximum. Intersection is not possible. A bucket holds a maximum value, not *which* elements landed there, so there is no way to tell whether bucket *i* in A and bucket *i* in B recorded the same user.

The usual workaround is inclusion–exclusion: recover the intersection from `|A| + |B| − |A∪B|`. This is mathematically valid and practically unusable. When A and B overlap heavily, the terms being subtracted are large numbers of similar magnitude; the absolute error stays the same while the relative error is amplified by an order of magnitude or more. And a condition tree with several levels of nesting makes the number of inclusion–exclusion terms grow exponentially, at which point error control is gone entirely. Audience segmentation is precisely the high-overlap, deeply-nested case.

So the selection problem becomes clear: we need something as compact as HLL and equally mergeable, but with native support for intersection and difference *at the data structure level*. That is Theta Sketch.

---

## 2. Theta Sketch: A Hash Set With a Capacity Ceiling

### 2.1 Structure and estimator

A Theta Sketch is a hash set with a capacity ceiling. Its theoretical framework is due to Dasgupta et al. (2016), and the core idea traces back to the earlier KMV (K Minimum Values) sketch (Bar-Yossef et al., 2002).

Exact deduplication is usually done with a `HashSet<long>`: hash each incoming user ID, insert it, and read the size at the end. The problem is that the set grows without bound.

Theta Sketch changes exactly one thing: give that hash set a capacity ceiling k, and when it overflows, discard the largest hash values and keep only the k smallest.

- A 64-bit hash function maps each user ID to a value uniformly distributed over `[0, 1)`.
- The same user ID always maps to the same value, so deduplication happens at the hashing step — independent of insertion order or repetition.
- Once k values are stored, every new insertion evicts the current maximum.

No matter how much data arrives, the structure holds at most k 64-bit integers. At k = 16384 that is roughly 128 KB — and it stays roughly 128 KB forever.

The remaining question: given only k hash values, how do you recover the original number of distinct elements? The key is remembering the threshold that got evicted — that is **θ**.

The meaning of θ is direct: every element whose hash value is below θ was kept; everything at or above θ was discarded. When the sketch is empty or not yet full, θ = 1.0, which is equivalent to exact mode — nothing was thrown away.

Because hash values are uniform on `[0, 1)`, the probability of the event "hash value < θ" is exactly θ. In other words, θ is a deterministic, i.i.d. sampling rate. The estimator is therefore plain inverse-probability weighting:

> distinct count ≈ (number of retained hash values) ÷ θ

θ = 0.001 means about one in a thousand elements was retained; with 16,384 values in hand, the original cardinality is roughly 16.4 million.

### 2.2 Three engineering properties

| Property | What it means | Architectural consequence |
|---|---|---|
| Constant size | At most k hash values, independent of input volume | Storage budget can be planned precisely; it does not grow with traffic |
| Error depends only on k | Relative standard error ≈ 1/√k, independent of cardinality | k is the single accuracy knob, and it can go into an SLA |
| Mergeable | Two sketches combine into one without loss | Enables a layered pre-aggregate / re-aggregate-at-query-time architecture |

On the second property: quadruple k, halve the error, quadruple the size. That is a clean cost–accuracy curve.

On exact mode: at small volumes the sketch never overflows, θ stays at 1.0, and the estimate equals the truth. Adopting an approximate algorithm does not make small data spuriously inaccurate — a useful point when explaining this to business stakeholders.

### 2.3 Set operations

This is where Theta Sketch differs from HLL.

**Union.** Take the smaller of the two θ values as a common threshold, pool the hash values below that threshold from both sides and deduplicate (identical elements hash identically, so they merge naturally), then trim back to k if needed.

**Intersection.** Intersect the two sets of hash values directly and extrapolate using the common θ. HLL cannot do this, because Theta Sketch retains *actual hash values* while HLL retains per-bucket statistics.

**Difference.** Remove from A's hash values those present in B, then extrapolate with the common θ.

Reducing to a single common θ is the shared precondition for all three: the inverse-probability estimator is unbiased only when both sides are sampled from the same probability space. This also explains the pitfall in §5.1 — when two sketches have very different θ values, the common threshold is dragged down to the lower one and the effective sample size of the intersection collapses.

### 2.4 Preconditions and limits

**Every sketch that participates in a merge must use the same hash function and the same seed.** This is why a sketch produced by an offline Spark job can be read and merged by a different engine, and why today's sketch merges cleanly with one from three years ago. This cross-time, cross-system, cross-language binary mergeability is what separates Theta Sketch from ordinary random sampling — ordinary sampling cannot guarantee that two independent jobs sampled the same users, so it cannot deduplicate across them. Conversely, a seed mismatch produces a runtime error, and this is one of the most common deployment mistakes.

**Discarded information is unrecoverable.** A sketch contains no user IDs, only truncated hash values; the information loss is one-way. This is an asset for privacy compliance (a sketch typically does not constitute personal information on its own), but it also means the limitations in Section 5 cannot be worked around by storing a bit more.

---

## 3. The Engineering Pipeline: Slice, Pre-aggregate, Re-aggregate

This section addresses the practical questions: at what granularity do you build sketches, how many, and how do you combine them at query time.

The pipeline has three steps: build sketches offline at the finest slice granularity; at query time, merge along the time dimension first; then evaluate set operations along the condition tree.

### 3.1 Choosing the slice key

You do not build one sketch — you build one per cell of a multi-dimensional cube. The choice of slice key determines both the storage cost and the boundary of what the system can answer.

A typical slice key looks like:

```
date × entity ID × event name × attribute key × attribute value
```

Each cell stores one Theta Sketch containing the users who satisfy all conditions of that cell.

Two design principles pull in opposite directions. The slice key must cover every field that could appear in a query condition, because at query time you can only combine existing cells — you cannot split them retroactively. But the finer the slice key, the more cells, and the higher the cost. This is a pure cost-versus-flexibility trade-off.

One problem must be handled explicitly: dimension-value explosion. If an attribute's cardinality approaches the event count — for example, when a millisecond timestamp is reported as an event attribute — each cell ends up holding a single record and the whole design collapses: the number of sketches explodes, every sketch degenerates to exact mode, and scan ranges become unbounded.

The remedy is to prune attributes in the pre-aggregation job using statistical criteria that filter out high-cardinality noise. AppsFlyer's criteria are: the attribute has fewer than 100 distinct values, and the ratio of distinct values to occurrences is below 0.1 (Cohen, 2020). Attributes that fail are ignored and excluded from slicing. Fundamentally this is storage cost control.

### 3.2 Building sketches offline

Daily granularity is the right choice for most cases, because it is the coarsest granularity that still preserves query flexibility. Queries by week, by month, or over any arbitrary date range can all be served from daily sketches, whereas hourly granularity multiplies the cell count by 24.

The job runs once per day as a batch: read yesterday's raw events, group by slice key, feed user IDs one at a time into a Theta Sketch per group, and serialize the result to a byte array in the storage layer.

One practical recommendation is to also generate an "all-attributes merged" layer — a sketch per event that unions all of that event's attribute combinations in advance. Queries without attribute filters are typically the highest-frequency class, and with this layer they need a single point lookup instead of scanning and merging many rows. This is a standard read/write trade-off: spend a little more on write, save a lot on read.

### 3.3 Two-level aggregation at query time

The conditions a user defines are parsed into a tree, and evaluation happens at two levels.

**The first level is merging along the time dimension.** Each leaf condition carries a date range. The system retrieves the sketch for each day in that range and unions them, producing the user set for that condition over the whole range. Because sketches are mergeable, the distinct user count for any date range can be computed on the fly from daily sketches — this is precisely why pre-aggregated results remain reusable across time. If a leaf condition also carries an attribute filter, multiple rows may match on the same day, and those are unioned as well.

**The second level is evaluating the condition tree.** With a sketch for each leaf in hand, the unions, intersections, and differences on the tree are evaluated bottom-up, and the estimate at the root is the final audience size.

Both levels operate only on sketches — the operands are byte arrays of a few hundred kilobytes, not billions of detail rows. That is the direct reason latency drops from minutes to milliseconds.

### 3.4 The cost model

An exact approach that supports distinct counting over arbitrary dimension combinations must retain user-level detail. Its storage grows linearly with event volume, typically landing in the petabyte range. A sketch-based approach stores (number of slice-key combinations) × (retention days) × (sketch size), typically landing in the terabyte range. On the query side, the exact approach requires a deduplicating shuffle over detail rows and takes minutes; the sketch approach reads a set of byte arrays and merges them, taking milliseconds.

What matters here is not the compression ratio but the change in the *nature* of the cost model: **the cost of a sketch-based system is driven by the number of slice-key combinations, not by event volume.** Ten times the traffic barely changes sketch storage; but adding a few filterable dimensions to the product can multiply the combination count a hundredfold.

For anyone doing capacity planning, this is a shift in mindset: once you adopt sketches, your storage budget is no longer determined by traffic — it is determined by the product's filter design. The attribute pruning in §3.1 is, at bottom, managing that budget.

---

## 4. Measurements: How Accurate, How Cheap, How Fast

All figures below were measured with the official Apache DataSketches Python library. Code in Appendix A.

### 4.1 Accuracy and compression

| True cardinality | k | Estimate | Relative error | Sketch size | Exact storage (hashes only) | Compression |
|---:|---:|---:|---:|---:|---:|---:|
| 100,000 | 4,096 | 100,052 | +0.05% | 33 KB | 781 KB | 23× |
| 1,000,000 | 4,096 | 997,666 | −0.23% | 51 KB | 7.6 MB | 155× |
| 1,000,000 | 16,384 | 988,724 | −1.13% | 179 KB | 7.6 MB | 44× |
| 10,000,000 | 4,096 | 9,834,825 | −1.65% | 41 KB | 76 MB | 1,908× |
| 10,000,000 | 16,384 | 9,959,395 | −0.41% | 147 KB | 76 MB | 533× |
| 10,000,000 | 65,536 | 10,024,064 | +0.24% | 519 KB | 76 MB | 151× |

The column to watch is sketch size. As cardinality grows from 100K to 10M — a factor of 100 — sketch size at fixed k barely moves, and the compression ratio climbs from 23× to 1,908×. The larger the data, the better this technique pays off, which is why it is so widely adopted at very large scale.

### 4.2 Testing the error distribution

The unsettling thing about approximate algorithms is not knowing how wrong any given answer is. Theta Sketch behaves well here: the estimator is unbiased (the long-run average converges to the truth, with no systematic skew in either direction) and the error distribution is close to normal (Apache DataSketches, 2025).

25 independent trials per k, true cardinality 200,000:

| k | Theoretical RSE (1/√k) | Observed RSE | Mean error (bias check) | Max absolute error | Within ±2 RSE |
|---:|---:|---:|---:|---:|---:|
| 1,024 | 3.13% | 2.57% | +0.43% | 6.87% | 96% |
| 4,096 | 1.56% | 1.20% | +0.02% | 2.82% | 100% |
| 16,384 | 0.78% | 0.72% | +0.10% | 1.59% | 96% |

Observed error never exceeds the theoretical bound, mean error is close to zero, and roughly 95% of results fall within two standard errors. This means you can hand stakeholders a number *with a confidence interval* rather than an estimate of unknown provenance.

### 4.3 Theta vs. HLL vs. an exact set

3 million records:

| Approach | Space | Build time | Estimate | Error | Set operations |
|---|---:|---:|---:|---:|---|
| Exact Python set | 316 MB | 0.99 s | 3,000,000 | 0% | Yes, but not compressible or distributed-mergeable |
| Theta k=16384 | 153 KB | 0.31 s | 2,973,630 | −0.88% | Union / intersection / difference |
| HLL lgK=14 | 16 KB | 0.31 s | 2,991,501 | −0.28% | Union only |

Three conclusions. Theta saves roughly 2,000× the space of the exact approach and is 3× faster to build. Theta is *not* the cheapest — at comparable parameters HLL is 9.6× smaller and was more accurate in this run. And the entire reason Theta exists is the last column.

This table confirms the selection logic from §1.3: if the business only needs unions, choose HLL; the 10× size premium is only worth paying when you need intersection and difference.

### 4.4 Merge performance

Merging 100 daily sketches (5 million records total) into one:

| Union k | Time | Estimate | Error | 95% CI | Covers truth |
|---:|---:|---:|---:|---|:---:|
| 16,384 | 8 ms | 5,041,781 | +0.84% | [4,963,589, 5,121,202] | Yes |
| 65,536 | 27 ms | 5,016,124 | +0.32% | [4,977,304, 5,055,246] | Yes |

Single-digit to low-double-digit milliseconds is what makes the "merge along the time dimension" step in §3.3 feasible at query time. Note that the union operator has its own k, which becomes an upper bound on the accuracy of the merged result — a point that resurfaces in §6.2.

### 4.5 How set operations behave

Two sets of one million each, varying the degree of overlap (k = 16,384):

| True overlap | Overlap ratio | Intersection estimate | Intersection error | Difference (A−B) error |
|---:|---:|---:|---:|---:|
| 1,000,000 | 100% | 982,674 | −1.7% | — |
| 500,000 | 50% | 489,954 | −2.0% | −1.4% |
| 100,000 | 10% | 96,241 | −3.8% | −1.5% |
| 10,000 | 1% | 9,397 | −6.0% | −1.7% |
| 1,000 | 0.1% | 954 | −4.6% | −1.7% |
| 100 | 0.01% | 173 | +73.4% | −1.8% |

Difference is very stable — the error stays around 1.7% regardless of overlap. Intersection degrades noticeably once the overlap ratio drops below about one in a thousand. Which leads to the next section.

---

## 5. Four Things to Know Before You Ship

### 5.1 Intersection error gets amplified

This is where Theta Sketch most often goes wrong in production. Measured: a set of 10 million intersected with a smaller set fully contained within it (k = 16,384, so the true intersection equals the size of the smaller set):

| \|A\| | \|B\| | True intersection | Estimate | Relative error |
|---:|---:|---:|---:|---:|
| 10,000,000 | 1,000,000 | 1,000,000 | 1,005,086 | +0.5% |
| 10,000,000 | 100,000 | 100,000 | 106,267 | +6.3% |
| 10,000,000 | 10,000 | 10,000 | 12,564 | +25.6% |
| 10,000,000 | 1,000 | 1,000 | 2,094 | +109.4% |

The cause is the common threshold from §2.3. A's θ has been driven extremely low — roughly one in ten thousand elements retained — so the intersection can only be built on that very sparse sample, and the small set may have no sampled elements at all.

The mitigation is to raise k, but the cost is linear:

| k | Sketch A size | ∩ 100K | ∩ 10K | ∩ 1K |
|---:|---:|---:|---:|---:|
| 2¹⁴ | 147 KB | +6.3% | +25.6% | +109.4% |
| 2²⁰ | 11.6 MB | −0.5% | −1.8% | +11.9% |

Raising k by 64× brings the small-intersection error down from 109% to 12%, but a single sketch grows from 150 KB to 11.6 MB. With a few million sketches in the system, that is the difference between terabytes and petabytes.

The management implication: if the product needs to support long-tail audience definitions that resolve to only a few hundred people, Theta Sketch will return unreliable numbers. Those queries either need an exact path, or the UI should label the result as too small to be reliable.

### 5.2 k is a one-way architectural decision

k determines accuracy, size, and cost — and it can only be lowered after the fact, never raised. If you have two years of history stored at k = 4,096, you cannot move to k = 65,536. The information is gone; the only option is to rescan the raw data and backfill.

So k has to be settled with the business before launch. A common approach is tiering: large k for hot, high-value slices, small k for the long tail.

### 5.3 The numbers won't reconcile

The largest cost of an approximate system is usually not technical but organizational. The same query can return different results on two executions, especially when the distributed merge order is not fixed. A DAU figure in a report that differs by 1% from the DAU in a BI dashboard will be questioned repeatedly. And approximate numbers cannot be used for finance, billing, or compliance.

Boundaries need to be set in advance: approximate numbers for exploration and decision-making, exact numbers for settlement and external reporting. It also helps to display estimates as "≈ 4.7M" rather than "4,712,389" — a small formatting choice that removes a great deal of unnecessary argument.

### 5.4 It answers "how many," not "who"

A sketch discards most of the original information. You cannot ask whether a particular user is in the audience, and you cannot reverse a sketch into a targetable list of user IDs.

The standard solution is two-phase: use sketches for interactive size estimation with millisecond latency, then run an exact offline job to materialize the actual list once the user confirms, on the order of minutes. This is also the most natural shape for an audience segmentation product.

---

## 6. Production Practice and Ecosystem

Back to the product from the opening. AppsFlyer's Audiences Segmentation has two generations of publicly documented architecture spanning about a decade, and the evolution itself is more informative than either architecture in isolation.

### 6.1 First generation: Spark + HBase

The first generation worked like this: an Airflow-scheduled daily Spark job scanned the S3 data lake, built sketches by slice key, and bulk-loaded them into HBase; an API service queried HBase, retrieved the sketches, and performed set operations in the application layer (Cohen, 2020).

![First-generation architecture: Spark builds sketches, loads into HBase, API service queries](https://d2908q01vomqb2.cloudfront.net/b6692ea5df920cad691c20319a6fffd7a4a766b8/2024/08/01/BDB-3551-2-1.png)

*Figure 2: First-generation architecture. Source: Pelts et al., 2024*

HBase matched the access pattern: writes are daily bulk loads, reads are point lookups and short range scans, and the data is schemaless with extremely sparse columns. HBase's sparse column model and lexicographic row-key scans fit well.

**Accuracy in production**, measured across a sample of 7,000 real-world queries against exact audience sizes computed offline (Cohen, 2020):

| Metric | Value |
|---|---|
| Queries with error below 1% | ~40% |
| Queries with error at or below 10% | 87% |
| Average approximation error | 6% |
| Within the same order of magnitude as truth | 99.7% |

**Latency**, measured client-side over three days of production traffic (a separate measurement from the accuracy sample):

| Percentile | p50 | p90 | p95 | p99 |
|---|---|---|---|---|
| Query latency | 50 ms | 323 ms | 500 ms | 892 ms |

At the time of writing — after three years of uptime — the HBase deployment spanned 50 nodes and stored 15 TB, mostly sketches.

The number worth pausing on is that 6% average error, far above the ~1% theoretical error of a single sketch. This is the §5.1 phenomenon showing up in real workloads: multi-level set operations accumulate and amplify error at each step. It makes one thing explicit — laboratory accuracy and production accuracy are not the same thing, and an end-to-end error evaluation against the real query distribution is necessary before launch.

### 6.2 Second generation: S3 + Parquet + Athena

Roughly three years later the workload had grown to 23 TB, the HBase architecture was struggling to meet latency SLAs, and operational cost was high. The team rebuilt it: remove HBase entirely, store sketches as Parquet files on S3, and query them directly with Amazon Athena (Pelts et al., 2024).

![Second-generation architecture: HBase removed, Athena queries Parquet on S3](https://d2908q01vomqb2.cloudfront.net/b6692ea5df920cad691c20319a6fffd7a4a766b8/2024/08/01/BDB-3551-3-1.png)

*Figure 3: Second-generation architecture. Source: Pelts et al., 2024*

Several representative problems came up during the migration.

**Partition count explosion.** Keeping the date-plus-app-ID partitioning and scaling to 10,000 apps left 7.3 million partitions in the metadata catalog; loading partition metadata alone took 10–15 seconds during query planning. The fix was partition projection — instead of loading a partition list from the catalog, derive partitions on the fly from configured rules. The team identified this as the change that made the whole approach viable.

**Merging early costs accuracy.** The team tried unioning 30 daily sketches into one monthly sketch to cut row count. Row count did drop by 97%, but the accuracy loss was unacceptable and the idea was dropped. This matches the observation in §4.4: the union operator's own k becomes a new accuracy ceiling. Mergeability is free; merging *early* is not — it also gives up the ability to drill back down to daily granularity.

**Result sets too large.** A single query could return millions of sketch rows, making result transfer the bottleneck. The team restructured the schema, splitting what had been multiple key-value combinations packed into one sketch, which substantially reduced result rows and improved overall query time by 90%.

**Mergeability as an optimization lever.** Long date-range queries were split into several shorter ranges executed in parallel and then merged, improving performance by about 20%. Because sketches are mergeable, splitting and recombining leaves the result unchanged.

The migration delivered roughly a 10% improvement in query performance and an 80% reduction in monthly cost.

### 6.3 What the two generations tell us

Between these two generations, the storage engine went from HBase to S3 plus Parquet, the query layer went from a custom API service to a serverless query engine, the schema was restructured, the partitioning strategy was thrown out and redone, and two full years of data were backfilled.

The 150 KB sketch byte array did not change. Because it is self-contained, serializable, and binary-compatible across systems, it moved from HBase to Parquet without touching the business logic.

The lesson for selection: **portability of the data structure is itself a value worth accounting for.** Choosing the right data structure outlasts choosing the right database.

### 6.4 Ecosystem: you probably don't need to build this yourself

That portability is not unique to AppsFlyer — it comes from the unified binary format defined by Apache DataSketches. A sketch produced in Spark can be queried by Druid, read by BigQuery, and merged by ClickHouse, which makes the layered "offline pre-aggregation plus online query" architecture straightforward to implement.

Systems with native integration or official extensions include:

| System | Form of support |
|---|---|
| Apache Druid | Native aggregators; build at ingestion, merge at query time; full set expressions in SQL |
| Apache Pinot | Native support; set expressions available in SQL |
| ClickHouse | Built-in `uniqTheta` function family; sketch states can be materialized for pre-aggregation |
| Trino / Amazon Athena | DataSketches connector reads and merges sketches built upstream |
| PrestoDB | Built-in `sketch_theta*` function family |
| Spark / Hive / Pig | Official UDFs |
| Google BigQuery / PostgreSQL | Official extensions |
| Databricks | SQL sketch function family |

Client libraries cover Java, C++, Python, Rust, and Go, with an interoperable binary format.

Three recommendations:

1. **If your data platform already supports it, don't build your own.** Sketches have many edge cases — empty sketches, the switch out of exact mode, seed validation, serialization version compatibility, sampling mode — and the official libraries handle them more reliably than a home-grown implementation.
2. **Note that engines differ in which set operations they expose.** Some surface union, intersection, and difference fully in SQL; others provide only union and cardinality estimation, leaving intersection and difference to the application layer. The latter means shipping large volumes of sketch bytes back to the application — exactly the source of the oversized-result-set problem in §6.2. Factor this into the decision.
3. **If you only need unions, don't use Theta.** Back to §4.3: at comparable parameters, HLL or CPC sketches are an order of magnitude smaller. Theta's size premium is only worth paying when intersection and difference are genuinely required.

---

## 7. Closing

Theta Sketch is a specific trade: roughly 1% error — quantifiable, predictable, and unbiased — in exchange for three to four orders of magnitude in storage savings, plus mergeability and set operations.

For an engineering manager, the question to answer is never whether the algorithm is accurate. It is these three:

1. **Is the business decision sensitive to that 1%?** If "about 4.7 million people" and "4,712,389 people" lead to the same decision, the latter is just a more expensive version of the former.
2. **Can the organization accept that the numbers will move?** This is usually harder than the technical integration.
3. **What share of your query distribution consists of small intersections?** This determines the gap between laboratory accuracy and production accuracy — AppsFlyer's answer was that 1% became 6%.

Settle those three, and what remains is implementation — which the industry has already made fairly mature.

---

## Appendix A: Experiment Code

Environment: Python 3 with the official Apache DataSketches library.

```bash
pip install datasketches
```

### A.1 Basic usage

```python
from datasketches import (
    update_theta_sketch, theta_union, theta_intersection, theta_a_not_b
)

# Build a sketch. lg_k=14 means k = 2^14 = 16384 nominal entries.
sk = update_theta_sketch(14)
for uid in user_ids:
    sk.update(uid)              # hashing dedups automatically

print(sk.get_estimate())        # estimated distinct count
print(sk.get_lower_bound(2))    # 95% confidence lower bound
print(sk.get_upper_bound(2))    # 95% confidence upper bound

compact = sk.compact()          # read-only, serializable form
blob = compact.serialize()      # persist to S3 / HBase / Parquet / Druid
```

### A.2 Set operations

```python
# Union: |A ∪ B|
u = theta_union()
u.update(sketch_a)
u.update(sketch_b)
print(u.get_result().get_estimate())

# Intersection: |A ∩ B|
i = theta_intersection()
i.update(sketch_a)
i.update(sketch_b)
print(i.get_result().get_estimate())

# Difference: |A − B|
d = theta_a_not_b()
print(d.compute(sketch_a, sketch_b).get_estimate())
```

### A.3 Experiment 1 — accuracy and compression (§4.1)

```python
from datasketches import update_theta_sketch

# Sweep cardinality N and nominal entries k; report error and compression.
for N in [100_000, 1_000_000, 10_000_000]:
    for lgk in [12, 14, 16]:
        sk = update_theta_sketch(lgk)
        for i in range(N):
            sk.update(f"user_{i}")
        est = sk.get_estimate()
        sketch_bytes = len(sk.compact().serialize())
        # Most compact exact representation: one 64-bit hash per element
        exact_bytes = N * 8
        print(N, 2**lgk, est, est / N - 1,
              sketch_bytes, exact_bytes, exact_bytes / sketch_bytes)
```

### A.4 Experiment 2 — error distribution (§4.2)

```python
import math, statistics
from datasketches import update_theta_sketch

N, TRIALS = 200_000, 25

# Verify: (a) estimator is unbiased, (b) observed RSE tracks 1/sqrt(k-1).
for lgk in [10, 12, 14]:
    k = 2 ** lgk
    errors = []
    for t in range(TRIALS):
        sk = update_theta_sketch(lgk)
        for i in range(N):
            sk.update(f"t{t}_u{i}")     # distinct key space per trial
        errors.append(sk.get_estimate() / N - 1)
    observed_rse = math.sqrt(sum(e * e for e in errors) / len(errors))
    theoretical = 1 / math.sqrt(k - 1)
    within_2rse = sum(1 for e in errors if abs(e) < 2 * theoretical) / len(errors)
    print(k, theoretical, observed_rse,
          statistics.mean(errors),       # ~0 confirms unbiasedness
          max(abs(e) for e in errors), within_2rse)
```

### A.5 Experiment 3 — set operation error vs. overlap (§4.5)

```python
from datasketches import update_theta_sketch, theta_intersection, theta_a_not_b

LGK = 14

def build(items, lgk=LGK):
    """Build a compact Theta sketch from an iterable."""
    s = update_theta_sketch(lgk)
    for x in items:
        s.update(x)
    return s.compact()

NA = NB = 1_000_000
for overlap in [1_000_000, 500_000, 100_000, 10_000, 1_000, 100]:
    offset = NA - overlap                       # controls |A ∩ B|
    A = build(f"u{i}" for i in range(NA))
    B = build(f"u{i}" for i in range(offset, offset + NB))

    it = theta_intersection(); it.update(A); it.update(B)
    intersect_est = it.get_result().get_estimate()

    diff_est = theta_a_not_b().compute(A, B).get_estimate()

    print(overlap, intersect_est, intersect_est / overlap - 1,
          diff_est, diff_est / (NA - overlap) - 1)
```

### A.6 Experiment 4 — three-way comparison and merge throughput (§4.3 / §4.4)

```python
import time, sys
from datasketches import update_theta_sketch, hll_sketch, theta_union

N = 3_000_000
data = [f"user_{i}" for i in range(N)]

# --- Exact baseline ---
t = time.time(); exact = set(data); t_exact = time.time() - t

# --- Theta sketch ---
t = time.time()
sk = update_theta_sketch(14)
for x in data:
    sk.update(x)
t_theta = time.time() - t
theta_bytes = len(sk.compact().serialize())

# --- HLL sketch (union only, no set ops) ---
t = time.time()
h = hll_sketch(14)
for x in data:
    h.update(x)
t_hll = time.time() - t
hll_bytes = len(h.serialize_compact())

print(t_exact, t_theta, t_hll, theta_bytes, hll_bytes)

# --- Merge throughput: 100 daily sketches -> 1 ---
sketches = []
for j in range(100):
    s = update_theta_sketch(14)
    for i in range(50_000):
        s.update(f"g{j}_u{i}")          # disjoint key spaces -> true union = 5M
    sketches.append(s.compact())

for union_lgk in [14, 16]:
    t = time.time()
    u = theta_union(union_lgk)          # union accuracy is capped by its own k
    for s in sketches:
        u.update(s)
    result = u.get_result()
    print(union_lgk, (time.time() - t) * 1000, result.get_estimate(),
          result.get_lower_bound(2), result.get_upper_bound(2))
```

### A.7 Experiment 5 — the large ∩ small failure mode (§5.1)

```python
from datasketches import update_theta_sketch, theta_intersection

def build(items, lgk):
    s = update_theta_sketch(lgk)
    for x in items:
        s.update(x)
    return s.compact()

# B is fully contained in A, so the true intersection size equals |B|.
# As |B| shrinks, A's low theta leaves almost no samples inside B.
for lgk in [14, 20]:
    A = build((f"u{i}" for i in range(10_000_000)), lgk)
    print("sketch A bytes:", len(A.serialize()))
    for nb in [1_000_000, 100_000, 10_000, 1_000]:
        B = build((f"u{i}" for i in range(nb)), lgk)
        it = theta_intersection(); it.update(A); it.update(B)
        est = it.get_result().get_estimate()
        print(lgk, nb, est, est / nb - 1)
```

> Reproduction note: absolute timings vary with hardware, but compression ratios, error magnitudes, and all relative comparisons are stable and reproducible. Measurements were taken single-threaded on CPU. A complete runnable script is available as `theta_sketch_experiments.py`.

---

## Appendix B: References

**Algorithms and theory**

- Bar-Yossef, Z., Jayram, T. S., Kumar, R., Sivakumar, D., & Trevisan, L. (2002). Counting distinct elements in a data stream. *RANDOM/APPROX 2002*.
- Flajolet, P., Fusy, É., Gandouet, O., & Meunier, F. (2007). HyperLogLog: the analysis of a near-optimal cardinality estimation algorithm. *AofA 2007*.
- Dasgupta, A., Lang, K., Rhodes, L., & Thaler, J. (2016). A framework for estimating stream expression cardinalities. *ICDT 2016*.
- Apache DataSketches. (2025). [Theta Sketch Framework](https://datasketches.apache.org/docs/Theta/ThetaSketchFramework.html) and [Basic Theta Sketch Accuracy](https://datasketches.apache.org/docs/Theta/ThetaAccuracy.html).

**Production case studies**

- Cohen, R. (2020). [Applied probability: counting large sets of unstructured events with Theta sketches](https://medium.com/appsflyerengineering/applied-probability-counting-large-set-of-unstructured-events-with-theta-sketches-b1464cd16c9a). *InfoQ / AppsFlyer Engineering*. (First-generation architecture: Spark + HBase; source of the accuracy and latency measurements in §6.1)
- Pelts, M., Kimchi, O., Safri, M., & Diamant, N. (2024). [How AppsFlyer modernized their interactive workload by moving to Amazon Athena and saved 80% of costs](https://aws.amazon.com/blogs/big-data/how-appsflyer-modernized-their-interactive-workload-by-moving-to-amazon-athena-and-saved-80-of-costs/). *AWS Big Data Blog*. (Second-generation architecture: S3 + Parquet + Athena; source of Figures 1–3)

**Engine integration documentation**

- [DataSketches functions](https://trino.io/docs/current/functions/datasketches.html) — Trino
- [Sketch functions](https://prestodb.io/docs/current/functions/sketch.html) — PrestoDB
- [uniqTheta](https://clickhouse.com/docs/sql-reference/aggregate-functions/reference/uniqthetasketch) — ClickHouse
- [Approximations with Theta sketches](https://druid.apache.org/docs/latest/tutorials/tutorial-sketches-theta/) — Apache Druid
- [Approximate answers, exact decisions: new sketch functions for analytics](https://www.databricks.com/blog/approximate-answers-exact-decisions-new-sketch-functions-analytics) — Databricks
