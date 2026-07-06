---
title: Why Credit Approval and Ad Auctions Are Secretly the Same Math Problem
date: 2021-08-15
tags:
  - machine-learning
---

A bank deciding whether to approve your loan, and an ad exchange deciding whether your bid wins an impression, look like they have nothing in common. One is regulated, slow-moving, and decades old. The other is milliseconds-fast, algorithmic, and invisible to almost everyone.

But if you strip away the domain language, they're solving the exact same statistical problem — and they hit the exact same trap.

## The trap: you only see half the picture

Here's the core issue. A bank trains a model to predict "will this applicant repay the loan?" using historical data. But that historical data only contains people the bank _actually approved_. Everyone who was rejected never got a loan, so the bank never observes whether they would have repaid it or not.

The model is trained on a biased slice of the population — the slice that already passed a filter — and then it gets used to make decisions about the _entire_ population, including people who look like the ones that were filtered out. This is called **reject inference** in credit risk, and it's a well-known, genuinely hard problem in the industry.

Now look at real-time bidding in programmatic advertising. A system predicts "what's the probability I win this auction at bid price X?" — a **winrate model**. But you only fully observe outcomes for auctions you _entered and won_. If you lost, you typically just learn "my bid was lower than the market price" — an inequality, not a number. If you never bid at all, you learn nothing.

Same shape. Same trap. A model trained on partial, filtered outcomes, then asked to make decisions across a much bigger space than it ever directly observed.

## Why this isn't just a footnote — it's the whole game

In both domains, this problem is invisible until it isn't. A model can report excellent offline accuracy — great AUC, good log-loss — and still be dangerously wrong in production, because the _evaluation set_ has the same bias as the _training set_. You're grading your own homework with an answer key you wrote yourself.

The failure mode is quiet, not loud. Nothing crashes. The credit model just slowly misprices risk for the population it's never seen. The winrate model just slowly mispredicts win probability outside the price range it usually bids in — which is exactly the range you'd want to explore if you're trying to find better deals.

And this is where it connects to a problem I care about a lot: **calibration**. A model can rank correctly (it knows applicant A is riskier than applicant B, or bid X is more likely to win than bid Y) while being badly calibrated (it says 70% when the true rate is 50%). Ranking errors are usually visible quickly. Calibration errors compound silently downstream — into loan pricing, reserve calculations, budget pacing, bidding strategy — because every one of those downstream systems assumes the probability _means what it says_.

## What both fields borrow from the same toolbox

Once you see the shared structure, the shared solutions make sense too:

- **Survival analysis**, originally built for "this patient hasn't died yet, but we don't know when they will," maps directly onto "this bid hasn't lost yet, we just know it's below some threshold we haven't observed." Both are censored-data problems in disguise.
- **Importance weighting / inverse propensity scoring** — reweighting your observed sample to better represent the true population — shows up in both reject inference and in correcting winrate models for the fact that you don't bid uniformly across all price points.
- **Calibration methods under distribution shift** matter in both, because the population you're scored on tomorrow (new applicants, new market conditions) is never identical to the population you trained on yesterday.

None of these techniques are exotic. What's interesting is that they were developed somewhat independently in each field, refined against different pain, and then converge on the same math.

## The takeaway

If you work on any system that makes automated decisions from a probability — pricing, ranking, approving, bidding, routing — it's worth asking one uncomfortable question: _what part of the world does my training data simply never see?_ That blind spot is where reject inference, censored bidding, and every other version of this problem lives.

The fields that get this right don't just build good classifiers. They build systems that know the shape of what they don't know — and stay honest about it downstream.

---

_I work on the evaluation and calibration layer of real-time bidding systems, thinking about problems like this one at the intersection of ML methodology and production ad systems. If you work on similar selection-bias problems in credit, insurance, or hiring, I'd love to compare notes._