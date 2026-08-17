---
title: Merging Percentiles, from GK to T-digest
date: '2022-05-22'
draft: false
tags:
- Algorithms
- Distributed Computing
- Data Structures
categories:
- Technology
author:
- Sasha Qi
aliases:
- /posts/merging-percentiles-gk-to-t-digest/
---

Say you need to compute p99 latency for a service handling a few million requests an hour. The most direct approach: store every logged latency, sort them at query time, and read off the value at rank 0.99N. You build it and the log fills up memory within days. And the question isn't "yesterday." It's "the last seven days," "the last thirty days," and every window means sorting from scratch.

So don't store everything. Keep a bounded random sample instead. Each latency gets kept with some fixed probability, and memory stops scaling with data volume. You ship a version and the median comes out accurate. Then you check p99: out of ten thousand sampled points, maybe a hundred fall above that mark. Sampling treats every quantile the same, and the quantiles you actually care about — p99, p999 — are exactly where the sample runs thinnest.

You try a different angle: instead of dropping points at random, keep the ones that carry information, and tag each kept point with a range for its true rank, something like "this value's real rank sits between 120 and 135." A new point updates the ranges around it. Once a point's range gets narrow enough, you can merge it into a neighbor and free up space. Bounding the rank error to a provable limit under fixed memory is exactly the problem Greenwald and Khanna's 2001 design solves, later known as the GK algorithm, with space complexity O(1/ε log(εN)) [Greenwald and Khanna, 2001](https://dl.acm.org/doi/10.1145/375663.375670).

Your service is distributed, logs scattered across dozens of machines. You want each machine to keep its own GK summary and merge them at query time. When you try, the merge doesn't work: the rank range each point in a GK summary carries gets computed from its insertion order within that one stream. Two summaries built independently don't have ranges that line up, and forcing them together breaks the original error guarantee. GK assumes a single stream, read start to finish, not something you can stitch together afterward.

To merge cleanly, two summaries need to count against the same coordinate system instead of each keeping its own relative order. You fix the range latency values could fall into ahead of time, say [0, 10000] milliseconds, and build a complete binary tree over that range, one leaf per integer millisecond. Each latency increments the count at its leaf. Nodes whose count stays small enough get folded into their parent, repeating until the tree fits a size budget. Two machines each build a tree like this, and as long as they share the same range and the same node numbering, adding counts node by node gives you the merged result. Letting summaries collected across machines merge node by node while keeping a real error guarantee is exactly the problem Shrivastava, Buragohain, Agrawal, and Suri's 2004 design solves. It came out of sensor networks: sensors each collect their own readings and work under a tight power budget for radio, so summaries have to travel and merge over the network rather than converge on one machine [Shrivastava et al., 2004](https://arxiv.org/abs/cs/0408039). This structure is called q-digest.

Deploying it, you hit a snag: you need to know the range of possible latency values ahead of time, and you have to discretize it into integers. Normal latency mostly falls between a few milliseconds and a few hundred, but timeouts and retries stretch the tail out to tens of seconds. Either you build the tree deep enough to cover the extreme values, or you narrow the range and dump every timeout into the last bucket. Neither option sits well.

What you actually want is to skip fixing a range ahead of time and let the summary decide, from the data itself, where to split finely and where to split coarsely. Instead of a tree, use a set of "clusters," each one storing just two numbers: a mean and a count. A new value merges into its nearest cluster if that keeps the cluster from getting too big; otherwise it starts a cluster of its own. "Too big" isn't a fixed number. It depends on where the cluster sits in the distribution: clusters near the median can grow large, clusters near the ends stay small, and pushed to the extreme, a cluster near q=0 or q=1 holds exactly one raw point. The result is that error tracks q(1-q) instead of staying flat: p99, the quantile you actually care about, gets the sharpest estimate. Doing this without presetting a value range, while automatically concentrating precision at the tails, is exactly the problem Ted Dunning's design solves. He described it informally around 2013, and later formalized it with proofs alongside Otmar Ertl, under the name t-digest [Dunning and Ertl, 2019](https://arxiv.org/abs/1902.04023).

Turning "clusters near the ends stay small" into a rule you can compute means reaching for a different ruler. Define a monotonically increasing function k(q) that stretches the [0, 1] quantile axis into a new k-axis, then enforce one rule on every cluster: its span on the k-axis can't exceed 1, written as

k(q_right) − k(q_left) ≤ 1

where q_left and q_right are the two ends of the quantile range the cluster covers. Where k(q) is steep, a small stretch of q uses up the whole budget, so the cluster can only hold a few points. Where k(q) is flat, a wide stretch of q is needed to spend that same budget, so the cluster can hold many. The scale function t-digest uses most often is

k₁(q) = (δ / 2π) · arcsin(2q − 1)

arcsin is steep at both ends and flat in the middle, which is exactly the shape needed. δ is the compression parameter: turning it up trades size for accuracy.

![The k1 scale function, delta=20](/images/fig1-scale-function.png)
*The k₁ scale function, δ=20. The curve is k₁(q); the horizontal lines sit at integer values of k, and where they cross the curve projects down to a cluster boundary. Boundaries land around q ≈ 0.02, 0.09, 0.20, 0.35, 0.50, packed tighter toward the ends.*

Once δ is fixed, switching to a steeper ruler pushes the tail clusters down further. The t-digest paper gives a few more aggressive variants, with tail cluster weights up to two orders of magnitude smaller than k₁, at the cost of more complex implementation and interpolation.

![Maximum allowed cluster weight across scale functions](/images/fig2-scale-family.png)
*Maximum allowed cluster weight for each scale function, normalized at q=0.5, log-log axes. This plot is drawn directly from the closed-form expressions, no measured data involved.*

What this ruler buys is clearest with a concrete example. Take ten thousand samples from an exponential distribution and look only at the slowest 1.5%. Equal-weight bucketing fits just one bucket into that stretch, so everything in between gets a straight line through it, while the real curve bends sharply there. Switch to t-digest's clustering rule and the same stretch splits into five clusters, with sample counts tapering to 71, 52, 33, 14, 1. That last cluster holds a single point, so there's no interpolation error left at all.

![Tail interpolation, equal-weight bucketing versus t-digest](/images/fig3-tail-interpolation.png)
*10,000 samples from Exponential(1), the last 1.5% of the right tail. The gray line is the empirical CDF, the blue line is the CDF reconstructed by linear interpolation between centroids, with each cluster's sample count labeled. Left: equal-weight bucketing, 100 samples per bucket. Right: t-digest clustering, δ=100.*

Merging two t-digests works about how you'd guess: combine the clusters from both into one list sorted by mean, then run that list back through the same clustering process with the same size rule. The process doesn't distinguish a cluster that started as one raw point from one that already absorbed ten thousand, so the merged result behaves the same as building one digest from the union of the two original datasets, with no extra bookkeeping.

That description simplifies one thing. A digest built by merging two others isn't, strictly, the same object as one built by feeding in all the raw data at once. Two clusters count as strictly ordered only if cluster A comes before cluster B and every sample in A is less than or equal to every sample in B. Clustering sorted data in one pass does produce strictly ordered clusters. Merging breaks that: two centroids sitting close together from different digests can end up next to each other with overlapping ranges, where the largest sample in the earlier cluster is bigger than the smallest sample in the one after it.

![Weak ordering after a merge](/images/fig4-weak-ordering.png)
*Illustration, not measured data. Adjacent clusters' value ranges overlap after a merge; the shaded region sketches that overlap.*

The paper's own words: in practice, merged digests still give accurate estimates, but "we do not yet have a good understanding of how weak this ordering can become." That's an empirical observation, not a theorem.

A compression parameter, usually called delta, sets how many clusters the whole digest can hold. Turning it up buys more accuracy at the cost of a bigger digest, and that tradeoff is left to whoever builds the thing.

At this point the original problem is solved: bounded memory, mergeable, no need to know the value range ahead of time, and accurate estimates at tail quantiles like p99. But dig into the early history of t-digest and you'll find it ran in production for years without a rigorous answer to "why doesn't this thing grow unbounded" or "why does this clustering rule hold the error guarantee." People adopted it because it performed well on real data. The 2019 paper with Ertl filled part of that gap: proofs that several concrete scale functions preserve the invariants a digest needs, tight bounds on how large a digest can grow, and better interpolation between the single-point clusters at the extreme tails, where earlier versions blurred exactly the precision the structure exists to keep [Dunning and Ertl, 2019](https://arxiv.org/abs/1902.04023).

This has since found wide adoption. Elasticsearch runs its percentile aggregation on t-digest by default [Elastic, percentile aggregation docs](https://www.elastic.co/docs/reference/aggregations/search-aggregations-metrics-percentile-aggregation). Apache Druid uses it for approximate percentile aggregation over event streams. Presto and Trino expose a tdigest column type with functions built directly on it [Presto, tdigest functions](https://prestodb.io/docs/current/functions/tdigest.html). Apache Arrow's C++ library and Facebook's Folly each carry their own implementation, and Redis Stack added one through RedisBloom. The reference Java implementation adds a point in about 140 nanoseconds, and a high-accuracy digest serializes down to a few kilobytes, small enough that shipping one over the network or holding thousands per query is routine [tdunning/t-digest, GitHub](https://github.com/tdunning/t-digest).

Getting this far also makes clear what t-digest trades away. Every step of GK comes with a proof written into the paper: no matter the input order or distribution, the rank error never exceeds ε. t-digest takes a different path. Its accuracy comes from extensive testing on real datasets, and since 2019 from proofs that its clustering rules preserve their own invariants, but those proofs cover the construction process, not the weakly ordered state that shows up after a merge. In 2021, Cormode and coauthors opened that gap up systematically: they can construct inputs that push t-digest's error arbitrarily high, and it doesn't take a deliberately adversarial input to do it. Ordinary i.i.d. sampling from a sufficiently non-uniform distribution is enough to throw it off [Cormode et al., KDD 2021](https://arxiv.org/abs/2102.09299).

The tail error isn't uniformly stable either. The t-digest paper measures relative error against q directly, and closer to q→0, relative error rises instead of falling. Their own words: "not well controlled."

![Error versus q, absolute and relative](/images/fig5-error-vs-q.png)
*n=10⁶ samples from Uniform(0,1), δ=100. The right panel shows relative error; toward q→0, the curves climb rather than keep falling.*

If what you need is a guarantee like "this number is within 5% of the true value," a structure built specifically for relative error, like DDSketch, is a better fit, at the cost of memory that scales with the dynamic range of the values rather than a fixed compression parameter δ [DDSketch, VLDB 2019](https://dl.acm.org/doi/abs/10.14778/3352063.3352135). The compression parameter itself still needs hand-tuning: turn it down and you save memory at the cost of accuracy, turn it up and accuracy improves at the cost of a bigger digest. The algorithm doesn't make that choice for you. What t-digest has going for it now is over a decade of production track record plus part of a formal proof added in 2019. What happens after a merge is still just a record, not a proof.

---

## References

- Greenwald, M., & Khanna, S. (2001). *Space-Efficient Online Computation of Quantile Summaries*. SIGMOD 2001. [ACM DL](https://dl.acm.org/doi/10.1145/375663.375670)
- Shrivastava, N., Buragohain, C., Agrawal, D., & Suri, S. (2004). *Medians and Beyond: New Aggregation Techniques for Sensor Networks*. SenSys 2004. [arXiv:cs/0408039](https://arxiv.org/abs/cs/0408039)
- Dunning, T., & Ertl, O. (2019). *Computing Extremely Accurate Quantiles Using t-Digests*. [arXiv:1902.04023](https://arxiv.org/abs/1902.04023)
- Cormode, G., Mishra, A., Ross, J., & Veselý, P. (2021). *Theory Meets Practice at the Median: A Worst Case Comparison of Relative Error Quantile Algorithms*. KDD 2021. [arXiv:2102.09299](https://arxiv.org/abs/2102.09299)
- Masson, C., Rim, J. E., & Lee, H. K. (2019). *DDSketch: A Fast and Fully-Mergeable Quantile Sketch with Relative-Error Guarantees*. PVLDB 12(12). [ACM DL](https://dl.acm.org/doi/abs/10.14778/3352063.3352135)
- Dunning, T. *t-digest*. Reference Java implementation. [GitHub](https://github.com/tdunning/t-digest)
- Elastic. *Percentiles aggregation*. Elasticsearch Reference. [Docs](https://www.elastic.co/docs/reference/aggregations/search-aggregations-metrics-percentile-aggregation)
- PrestoDB. *T-Digest Functions*. [Docs](https://prestodb.io/docs/current/functions/tdigest.html)
