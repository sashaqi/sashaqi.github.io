---
title: Four Shocks to Online Advertising
date: '2026-08-10'
draft: false
tags:
- online advertising
- RTB ads
categories:
- Technology
author:
- Sasha Qi
aliases:
- /posts/four-shocks-to-online-advertising/
---

## Fifteen years of technical evolution, from real-time bidding to machine audiences

---

On the afternoon of 10 August 2026, I ran a simple experiment.

From one machine, within a few minutes, I requested the same page from TIME's business section over and over. Each time I changed one thing: what I told the server I was.

As Chrome, I got 75 KB of full web page. As Safari, as Googlebot, as Bingbot, even as a bare `curl/8.0.0` — the same 75 KB.

Then I set the User-Agent to ClaudeBot. I got 7.8 KB, and the content-type came back as `text/markdown`. PerplexityBot, OpenAI's search crawler, GPTBot, ChatGPT-User: 7834, 7834, 7833, 7834 bytes. The same artifact.

![TIME returns different content by User-Agent](/images/fig1-time-two-products.png)

*One URL, one minute, one variable. Human browsers, two search crawlers, and bare curl all receive 75 KB of HTML. Five AI crawlers receive 7.8 KB of markdown.*

One URL. Two products.

I did not discover this. A developer ran the same test in early August and wrote it up ([Schmalbach, 2026](https://www.vincentschmalbach.com/time-serves-ai-bots-a-different-website/); [Digiday](https://digiday.com/media/time-has-started-serving-ads-to-ai-agents/)); I went to verify it for myself. The verification held. But I also tested nine other publishers, and that part turned out to be more interesting than the original finding.

**Five of the ten treat AI crawlers differently, using four distinct mechanisms.** TIME serves a different product. The New York Times refuses everyone. The Guardian and The Atlantic allow some vendors and block others. Forbes returns HTTP 402 to some crawlers.

That last one deserves a pause. HTTP 402 is Payment Required. The HTTP/1.1 spec marked it "reserved for future use," and for nearly thirty years it had no serious deployment. It is now in production — from two different vendors.

I will come back to all of this. The short version is that these findings point at one thing: a premise the online advertising industry has not had to question in fifteen years — that there is a human at the end of the chain — is failing.

To see why that matters, start with how the system took shape.

---

## I. A system built on two assumptions

Before real-time bidding, web advertising sold roughly like magazine pages: by placement, by period, in bulk, in advance. Around 2009, ad exchanges changed that. Every ad slot from every page load could be auctioned on its own. A user opens a page, the exchange broadcasts the opportunity, demand-side platforms bid within about a hundred milliseconds, the highest bid wins, the ad loads. All of it happens before the page finishes rendering.

Two conditions made this work. Both looked permanent at the time.

**The first was the auction.** Second-price auctions were standard: the winner pays the second-highest price. That mechanism has an attractive property — under idealized conditions of a single item, private values, and no budget constraint, bidding your true valuation is optimal.

Real ad systems meet none of those three conditions exactly. Advertisers have budgets, the same inventory is bid on repeatedly, valuations are not purely private. Truthful bidding was always an approximation. But it was a good enough approximation that the industry could treat bidding as a valuation problem: **predict whether this user will click and convert, and the bid follows. No strategic reasoning required.**

**The second was identity.** The browser cookie gave you a stable identifier that persisted across sites. With it, three things worked at once: you knew which audiences a person belonged to, you could cap how often they saw an ad, and you could connect an impression from three days ago to a purchase today. Targeting, frequency capping, attribution — all three grew from one cookie.

Together, these pointed the industry's technical effort at a single question: will this user click, and will they convert. If bidding is valuation, and valuation is probability times value, performance depends almost entirely on that probability.

Hence the classic papers of the era. Google published the internals of its production CTR system in 2013 — FTRL, memory savings, and, notably, calibration of predicted probabilities ([McMahan et al., KDD 2013](https://research.google.com/pubs/archive/41159.pdf)). Facebook published its boosted-trees-plus-logistic-regression pipeline in 2014 ([He et al., ADKDD 2014](https://dl.acm.org/doi/10.1145/2648584.2648589)). The same year, Criteo addressed an awkward problem: conversions arrive hours or days after the click, so your training negatives contain positives that simply have not happened yet. Their fix was to model conversion probability and the delay distribution jointly ([Chapelle, KDD 2014](http://wnzhang.net/share/rtb-papers/delayed-feedback.pdf)).

A second class of problem appeared then too, though it looked peripheral. Give an advertiser a daily budget and, uncontrolled, the system spends it in the first hour on morning traffic. Worse, the most efficient advertisers exhaust budget first and drop out, which hurts publisher revenue. LinkedIn published its pacing approach in 2014, splitting the day into intervals and allocating against global supply ([Agarwal et al., KDD 2014](http://www0.cs.ucl.ac.uk/staff/w.zhang/rtb-papers/linkedin-pacing.pdf)). Yahoo went further a year later: learn the delivery pace from offline and online data, and use a control system to adjust per-group rates, optimizing smoothness and performance together ([Xu et al., KDD 2015](https://arxiv.org/pdf/1506.05851)). Those controllers would matter far more than they appeared to.

That is where the first act ends. A system centered on prediction, founded on the cookie, running on second-price auctions. It worked, and nothing suggested it would change.

---

## II. Three shocks

The arrangement held for about eight years. Then three things happened in short order, each removing a condition the system depended on.

### The auction changed

Around 2017, header bidding spread among publishers, letting them solicit bids from several exchanges at once and breaking the old bidding order. The competitive shift pushed exchanges to first-price auctions around 2019. You bid, you win, you pay your bid.

This made a decade-old strategy wrong overnight. Under second price, bidding your valuation is near-optimal. Under first price, it means winning with zero surplus — you pay exactly what you thought it was worth. To capture margin, you have to shade down.

By how much? Shade too far and you lose. Not far enough and you gain nothing. The optimal point depends on the relationship between bid and win probability: find the point on that curve maximizing surplus times probability of winning. Budget constraints add a layer, but that is the shape.

Estimating that curve became mandatory. And here the industry hit something new: **you only observe the outcome when you win. When you lose, you see nothing.** Not "insufficient data," not "the model isn't good enough" — part of the observation is systematically hidden. And the hiding is determined by your own behavior. Bid conservatively, win less, and your visible samples concentrate in low-competition situations, which biases the curve.

Statistics has a name for this. Let W be the highest competing bid. Then `P(win | b) = P(W < b)` is the CDF of W, and the survival function `S(b) = P(W > b)` is its complement. **The win rate curve is the survival function of the competing-bid distribution.** Not an analogy — the same object.

In that language, the difference between the two auction formats is immediate. Under second price, the winner pays the second-highest price, so winning reveals W exactly while losing tells you only `W ≥ b`. That is **right-censored data**. Under first price, the winner pays their own bid, so even winning leaves W unknown, and observation collapses to a binary indicator of whether W falls below b — what survival analysis calls **current status data**. Strictly less information. That is the substantive change first price brought: not only did strategy have to change, the information available to estimate it shrank.

One caveat. Some exchanges return loss reasons or minimum-bid-to-win feedback, which restores part of the information. Practice sits between the two cases depending on your supply. The direction is clear.

Methods existed already. A 2015 approach used a mixture model: ordinary regression on won samples, censored likelihood on lost ones, weighted by win rate ([Wu et al., KDD 2015](https://dl.acm.org/doi/10.1145/2783258.2783276)). After the shift came general shading frameworks ([CIKM 2020](https://dl.acm.org/doi/10.1145/3340531.3412689)), deep distribution networks handling both cases ([Ren et al., 2021](https://arxiv.org/pdf/2107.06650)), and distributionally robust approaches ([2024](https://arxiv.org/pdf/2410.14864)).

These look like rival schools. They are not. **They are the same idea at different levels of flexibility** — all of them put censoring into the objective function, differing only in how strong an assumption they make about the distribution or functional form. Mixture models and Tobit assume a specific distribution. Gradient boosting and deep distribution networks relax the functional form. The end that assumes least — the nonparametric maximum likelihood estimator for current status data, whose solution is an isotonic regression — is not where the mainstream sits. That preference is worth examining, and I return to it.

### Identity collapsed

The second shock came slower and reached further.

Apple began restricting cross-site tracking in Safari in 2017. GDPR took effect in 2018. In 2021 Apple required explicit consent before tracking. Safari and Firefox moved to blocking third-party cookies by default. Chrome is more complicated: Google repeatedly delayed deprecation, then changed course in 2024, abandoning removal in favor of a user choice mechanism. Third-party cookies have not disappeared. But they are largely non-functional in Apple's ecosystem, and under regulatory and user-choice pressure their coverage and reliability keep eroding.

Targeting, frequency capping, and attribution all grew from that identifier, so all three degraded together. You no longer know the browser belongs to the person you want, how many times they have already seen the ad, or whether the impression three days ago and the purchase today are the same human.

Responses split two ways. One rebuilds identity: stitch fragments back together from behavioral and deterministic signals into a probabilistic identity graph. That graph is no longer a fact but an estimate, with coverage and error. The other routes around identity: if you cannot track individuals, recover population quantities without looking at individuals. Google's Virtual People maps observed device behavior onto a virtual population to estimate deduplicated reach ([Google Research](https://research.google/pubs/cross-media-measurement-with-virtual-people/)). Deduplicating across publishers, where neither side can hand over a user list, calls for noisy sketches — the problem Vector of Counts addresses ([Google Research](https://research.google/pubs/pub50153/)). The World Federation of Advertisers has evaluated this class of private estimators systematically ([WFA](https://github.com/world-federation-of-advertisers/cross_media_measurement_project_site/blob/master/public_papers/PRFE_results/Private%20Reach%20&%20Frequency%20Estimators%20Evaluation%20Results.md)).

The methods are elegant. But together they mark one change: **identity went from a given fact to an estimated quantity.** Another layer of uncertainty, where none had existed.

### The models got big

The third shock differs in kind. The first two took something away. This one was a capability gained.

From around 2020, deep learning displaced feature engineering and shallow models, and then the models kept growing to foundation-model scale. Per trade press, Meta deployed a retrieval engine called Andromeda in late 2024 to narrow every request to a candidate set from all active ads, and in mid-2025 deployed GEM at the ranking layer, far larger than its predecessors, reporting single-digit percentage lifts in conversion ([Search Engine Land](https://searchengineland.com/meta-ai-driven-advertising-system-andromeda-gem-468020)). These figures come from the platform via trade media, with experimental conditions and baselines undisclosed.

Bidding underwent a parallel shift. Early work used online reinforcement learning to optimize bidding parameters. Later work treats bidding as sequence generation, using conditional diffusion models ([Guo et al., KDD 2024](https://dl.acm.org/doi/10.1145/3637528.3671526)) or Decision Transformers over action history and environment state. Recent work targets feasibility under multiple constraints ([2026](https://arxiv.org/html/2602.08261)). The area is active, though for the newest papers I have read only abstracts.

The gains are real. Retrieval improvements make sense: selecting hundreds of candidates from tens of millions is a search problem over a huge space, observation is complete, and the bottleneck genuinely is representational capacity. And the ranking gains show that even in prediction, a stronger model still finds something.

**But one class of problem did not move, and in principle will not.**

How much to shade under first price still depends on a win-rate curve estimable only from censored data. Attribution still cannot produce a correct answer, because the quantity it needs was never in the data. Neither depends on model size.

### Looking back: a spectrum of recoverability

Line up the three shocks and a thread appears.

The first shock's difficulty: you cannot observe auctions you lost. The second: you cannot observe who is behind the browser. The third — the capability increase that looked most likely to help — helps least in exactly those places.

Look further back. Criteo's delayed feedback paper: conversions that have not happened yet cannot be observed at training time. Attribution: the counterfactual is never observed. The feedback loop: labels exist only on impressions you won and served, which you won because of your own policy, so the training data is filtered by yourself.

These four are usually lumped together as "data problems." They are **not on the same level.** The difference is recoverability.

**Delayed feedback is mildest.** The information arrives, just late. Wait and it is there, and the delay distribution itself can be modeled — which is why Chapelle's approach works. Not "absent from the data," but "not yet in the data."

**Censoring is next.** The information never arrives, but under reasonable distributional assumptions it is partially recoverable. Write the correct likelihood and you get some back. The cost is that conclusions now depend on assumptions.

**Selection bias follows.** Where propensity has overlapping support, you can correct — that is what off-policy evaluation is for. Where your policy never went, nothing helps.

**Missing counterfactuals are hardest.** Not "not observed" but "cannot in principle be obtained from observation." The same person cannot both see and not see the ad. That quantity requires intervention.

The spectrum has a useful property: **the left two fall within survival analysis's range.** Delayed feedback is time-to-event modeling, censoring is censored-data estimation, and both have mature toolkits. **The right two have no corresponding toolkit,** because what they need is not a better estimator but different data.

Lined up, the conclusion is clear: **responsiveness to a bigger model decreases monotonically along the spectrum.** Delayed feedback yields to better modeling. Censoring yields to a more correct likelihood. Selection bias yields where there is support. Missing counterfactuals do not yield at all — no model can conjure a world that never happened.

This depends on no performance number. It is a statement about information: **you cannot extract from data what is not in the data.** Whatever scaling delivered, the right end of the spectrum lies outside its reach.

Each shock got engineered around. But that right end has been sitting there for fifteen years.

---

## III. The fourth shock

Back to the experiment.

The three shocks share something nobody stated at the time. Rules changed, signals degraded, capabilities improved — but **the thing being priced never changed**. This system sold one human's attention. Impression, viewability, click-through, conversion, reach: all proxies for that.

That is what is now loosening.

### Four mechanisms

Ten publishers, one session, one method. Five treat AI crawlers differently, and they chose different routes.

**The New York Times is simplest**: all five AI crawlers get 403, humans and search crawlers get through. A flat refusal.

**The Guardian and The Atlantic discriminate by vendor**: ClaudeBot and PerplexityBot are blocked, while OpenAI's three crawlers get exactly the page a human gets.

**Forbes has three tiers**: ClaudeBot and GPTBot get 402; PerplexityBot and ChatGPT-User get a 7.2 KB stub against a 275 KB human page — headlines, links, summaries, nothing else; OAI-SearchBot gets the full page.

**TIME took a fourth route**, and the only one not aimed at restriction: give machines their own product, and put ads in it.

The two 402s deserve attention, because they run on entirely different infrastructure.

![The Atlantic returns 402 to ClaudeBot](/images/fig2-atlantic-402.png)

*Same moment: as Chrome, The Atlantic returns 200; as ClaudeBot, 402 Payment Required. The spec marked this code "reserved for future use," and for nearly thirty years it had no serious deployment.*

![Forbes returns 402 via TollBit](/images/fig3-forbes-tollbit.png)

*Forbes takes another route: a 307 redirect to a dedicated subdomain, then a 402 from a third-party service called TollBit, asking for a valid TollBit Token.*

One is a CDN capability. The other is a startup built for this business. **The same status code, two unrelated commercial paths — which suggests this is not one publisher's experiment. A supply-side market has formed.**

### Who gets blocked is a commercial question

Put the three selective publishers side by side and one pattern repeats: Anthropic's and Perplexity's crawlers are blocked or charged; OpenAI's are let through. Three independent publishers producing the same ordering is hard to explain technically. It maps onto the publicly known landscape of content licensing agreements. And the New York Times, which blocks everyone including OpenAI, maps onto its litigation with OpenAI.

**In other words, this young machine-audience market was never an open market.** Access runs on bilateral contracts, not bids. A new AI company that wants its crawler to read this content negotiates an agreement; it does not post a price.

### Declaration and behavior have come apart

The most counterintuitive finding comes from comparing robots.txt against observed behavior.

TIME's robots.txt contains **no rules for AI crawlers at all** — one `User-Agent: * Allow: /` plus a long list of URL-parameter hygiene for Googlebot. And TIME is the most sophisticated operator of the ten.

TIME does publish an `llms.txt`, last updated May 2025: disallow everything, with exceptions for OpenAI, Perplexity, Scale AI, and ElevenLabs, for training.

![TIME's llms.txt](/images/fig4-time-llms-txt.png)

*TIME's llms.txt: `disallow: *`, with OpenAI, Perplexity, Scale AI, and ElevenLabs on the exception list.*

**Anthropic is not on that list. Yet in testing, ClaudeBot received the same markdown and the same ad as the vendors that are.**

A plausible reading: llms.txt governs training, while ad-supported markdown is a different business. The licensing layer and the monetization layer have separated, and the existing protocols have no vocabulary for "you may not train on this, but you may read it, and I will serve you an ad."

The same split appears at Forbes, whose robots.txt declares `PerplexityBot: Disallow` while the observed response is a 200 with a stub. The declaration says stay out; the behavior says here is a lite version.

**The root problem is that robots.txt is a binary protocol — allow or deny — while reality already has at least four tiers: full, stub, paid, refused. The protocol cannot express a price, so the price ended up in an HTTP status code.**

### How the ads are served

Back to TIME. Inside the 7.8 KB machine version, alongside the article list, sits a block of sponsored content. This run caught Project Management Institute; the original report caught a bank, so more than one advertiser is buying.

Headers and body line up.

![TIME's response headers for AI crawlers](/images/fig5-mobian-headers.png)

*A format marker, an impression identifier, a token count (8350), and `cache-control: no-store`.*

![The ad tag inside the markdown](/images/fig6-mobian-ad-tag.png)

*The ad tag at line 24, carrying campaign and creative identifiers. Its `id` matches the `x-mobian-impression` header above: `4849a56f-f84b-47c4-a525-84fcfece124d`.*

Does that identifier change per request? Two requests answer it.

![Impression identifiers across two requests](/images/fig7-impression-ids.png)

*Same page, two consecutive requests, two different impression identifiers. With `no-store`, this confirms counting per request.*

This is not an ad pasted into a page. It is a complete ad-serving system — advertiser, campaign, creative version, per-request impression counting — **with the unit of measurement swapped from people to tokens.**

The creative is worth a look too. It is not copy; it is a series of fact tables. Founding year, membership size, certification holders, each row followed by a Source field. This is **a format optimized to be quoted by a model**, since models prefer to cite structured facts with attribution. It optimizes for something entirely different than an ad written for a person.

One more thing: five days before my test, the original report found GPTBot refused with a 406. In my run it received the same markdown and the same ad as everyone else. **The rules are still moving. Any observation is a snapshot.**

### Not the old problem in new clothes

Machine traffic is not new. Fake traffic, click farms, bots imitating humans — as old as online advertising, with mature taxonomies and a whole detection industry.

But the treatment is new. Invalid traffic logic is adversarial: identify, filter, exclude from billing. Of the five approaches above, only the New York Times fits that logic. The other four are doing something else: **charging different visitors different prices, or selling them different products.** That is market segmentation, not security.

The surrounding infrastructure is growing the same way. Cloudflare changed its default to blocking known AI crawlers unless they pay, and built a settlement marketplace ([Cloudflare](https://blog.cloudflare.com/introducing-pay-per-crawl/); [TechCrunch](https://techcrunch.com/2026/07/01/cloudflares-new-policy-pushes-ai-companies-to-pay-for-publishers-content/)) — The Atlantic's 402 is that system in production. At the protocol layer, two competing frameworks contest the standard for how advertising agents talk to each other ([AdCP](https://docs.adcontextprotocol.org/docs/faq); [IAB Tech Lab AAMP](https://iabtechlab.com/standards/aamp-agentic-advertising-management-protocols/)), though these remain intentions rather than settled facts.

### A question of magnitude

Until recently, the citable numbers on machine traffic came mostly from security vendors' annual reports, converging on estimates above half. Those deserve discounting: definitions vary widely, and the companies publishing them sell bot mitigation.

In early August 2026 a weightier claim appeared. On a quarterly earnings call, Cloudflare CFO Thomas Seifert noted that the company had predicted machines would overtake humans in 2027 and had been wrong — their measurements showed the crossover happened in May 2026. He then extrapolated: if trends hold, non-human traffic could reach a thousand times human traffic within five years. "Humans will be a rounding error on the internet, not because human traffic goes down, but that's just how fast we're seeing non-human traffic grow" ([The Register, 2026](https://www.theregister.com/networks/2026/08/07/humans-will-be-a-rounding-error-on-the-internet-says-cloudflare-exec/5284429)).

Cloudflare sits in front of a large share of web traffic, so it has a real vantage point. Discount it anyway: the company sells bot mitigation and pay-per-crawl, so large machine traffic suits it, and Seifert prefaced the number with "I have called it wrong at every point along the way."

The more important caveat is a misreading waiting to happen: **"traffic" here means requests, and requests are not audiences.** An agent may issue dozens of requests to read one article and hit a dozen sites to answer one question. Humans generate a different pattern entirely. A thousand times the requests is not a thousand times the audience. Advertising prices attention and decisions, not packets.

Even discounted heavily, the order of magnitude changes the outlook for one thing: **at ratios anywhere near this, filtering machines out and estimating a population from the remainder gets less tenable.** Not because filtering technology is weak, but because each order of magnitude tightens the accuracy required — while agents get better at passing for human and the signals to detect them are being removed.

### Reach takes the first hit

The clearest way to see the technical consequences is through reach.

Reach is the number of unique people a campaign touched. Paired with frequency, it is the core currency of brand advertising. Virtual People and Vector of Counts exist to estimate it well under degraded tracking.

Those methods share a premise that never needed stating: **there is a real population, observation is a biased sample of it, and the task is to recover population-level quantities.** All the ingenuity goes into that recovery under incomplete observation and no individual visibility.

Machine audiences undermine the premise not by making the sample more biased, but by making the population ambiguous.

There is a specific risk here, with a scope worth stating. Virtual People maps observed behavior onto a virtual population — an imputation under structural assumptions, designed to fill observational gaps. If agent behavior enters the observations, that mapping may project it into "people." And because imputation is the method's job, the contamination need not surface as a detectable outlier.

The limit: **this applies mainly to agents that do not declare themselves.** For crawlers like ClaudeBot that announce themselves, mainstream pipelines generally filter known crawlers before modeling. I could not find preprocessing details for Virtual People, so the honest statement is that the size of this risk depends on how much undeclared automated traffic exists — precisely the hardest thing to measure.

The deeper problem is definitional. An agent, acting for a real user, reads an article. Is that reach of one, or zero? If it read the sponsored FAQ, carried the information into its recommendation, and the user bought — then the ad reached that person in a causal sense, though the person saw nothing.

### Three paths

Three directions are available. This taxonomy is mine, not an industry consensus.

**Cleaning**: scrub machines out and hold the line that reach means people. This is the default and the most intuitive, but the magnitude problem squeezes it from both ends — the share to be identified grows while identification gets harder, since language-model-driven headless browsers now imitate mouse paths, dwell times, and scroll behavior, and privacy technology has removed part of the signal. More fundamentally, even perfect cleaning omits influence that happens through agents.

**Dual-track**: measure human and machine audiences separately, each with its own currency. Humans keep unique reach and frequency; machines get token consumption or citation counts. TIME appears to be heading here. It is easiest to build and fits commercial inertia. But there is no exchange rate between the currencies. Advertisers allocate budget, and allocation needs comparable measures. "A million people reached" and "thirty million tokens consumed" do not belong in one decision framework.

**Causal**: abandon reach as a count and return to influence on decisions. Measurement becomes randomized experimentation — withhold content from a fraction of agents, compare downstream conversion. This sidesteps the definitional problem and measures effect directly. It converts reach into an incrementality problem, which is where the industry was already heading. The cost is money and speed: experiments sacrifice traffic, need sample size, return slowly, and cannot run on every campaign.

### An inference from the experiment's limitation

The tests above carry a limitation I have to state: **I only forged the User-Agent. The requests did not come from any AI company's IP range.** Rigorous crawler verification uses reverse DNS or IP checks — Google publishes its method. So strictly, what I observed is how a server treats a request that *claims* to be a given crawler without proof, which is not necessarily how it treats the real ClaudeBot.

But that limitation points at something more interesting.

TIME served ad-bearing markdown to a request that merely claimed to be ClaudeBot, with no proof of identity. That request generated a real impression identifier and logged 8350 tokens.

In this young market, audience identity is asserted by an HTTP header the client can write freely, and impressions are counted per request. Together, those two facts mean **anyone can manufacture impressions with one line of curl.**

This is not a new problem. It is the invalid traffic problem from the human web, except that here even "is this a real audience" has degraded into a self-declared string. The human web spent twenty years and an entire detection industry failing to solve it.

**The machine-audience market did not route around the old market's difficulty. It inherited the same one.**

---

## IV. Where the money is going

The fourth shock is early, but the economics around it are already moving, and the direction matches the analysis.

Start with unpleasant numbers. As search began answering questions directly, publisher referral traffic collapsed. Reported figures show small publishers down roughly 60% over two years, mid-sized around 47%, large around 22%. In early 2026, more than six in ten searches reportedly ended without an external click, higher still on queries with an AI summary ([Digiday](https://digiday.com/media/google-ai-overviews-linked-to-25-drop-in-publisher-referral-traffic-new-data-shows/); [Search Engine Land](https://searchengineland.com/news-publishers-search-referrals-drop-report-467408)). Different sources, different methodologies, same direction.

Note this is a **supply-side** contraction. The thing that produces ad slots — humans opening pages — is decreasing.

But read only those numbers and you reach the wrong conclusion. Programmatic spend overall keeps growing: estimates put global spend near $755B in 2025 rising to about $821B in 2026, roughly 9% a year. The fastest-growing segment is retail media, at about 26% against roughly 8% for display, with the US market approaching $70B and about 18% of digital ad spend ([Basis](https://basis.com/blog/7-programmatic-advertising-trends-shaping-2026); [Adtelligent](https://adtelligent.com/blog/retail-media-market-outlook/)). Industry forecasts tilt optimistic, but methodology does not flip the sign on growth.

So the industry is not shrinking. Value is relocating. And why retail media grows this fast is worth a pause, because it is the same argument this article has been making.

Advertising on the open web means facing every difficulty from the second act: identity is estimated, conversion signals cross domains, attribution is a convention, counterfactuals are unobservable. Inside retail media, most of those **are not solved by better models. They are eliminated by business structure.** The retailer is where the purchase happens. It sees the impression and the purchase, needs no cross-domain stitching, and needs no attribution model to guess whom a conversion belongs to.

Put differently: the fastest-growing part of this industry is winning on information structure, not algorithms.

That is the most direct validation available for the earlier claim. If the bottleneck is information rather than modeling, expect **parties who can obtain better information by redrawing business boundaries to outperform those who can only improve models.** Capital flows look about like that.

The same logic supports a guess about the fourth shock. The core difficulty machine audiences create is "what are we pricing," and closed loops answer that more naturally: if an agent's recommendation leads to a purchase on the same platform, the causal chain is observable, and you never have to settle what reach equals. **On that reading, measurement for machine audiences gets solved first inside closed loops, not on the open web.** An inference, not a forecast — but consistent with the capital already moving.

---

## V. Questions without answers

The three shocks passed and the industry answered each. The fourth has barely started, and it differs in kind: the first three asked how to do the job well under worse conditions; this one asks what the job is. That cannot be engineered first and understood later.

Four questions look unavoidable. This is a personal selection, not a recognized agenda.

**What is the exchange rate between the two currencies?** As long as human and machine markets coexist, advertisers must allocate across them, and allocation needs comparable measures. There is neither an exchange rate nor a theory for building one. One route is the shared downstream: both point at conversion, so use incremental conversion as the common unit. That requires reliable incrementality on both sides, which does not exist. And there is a prior problem: if impressions on the machine side can be forged freely, the token-denominated half of the currency does not stand up in the first place.

**What does frequency mean for a model audience?** Frequency capping rests on human psychology — diminishing returns, then irritation. If the reader is a model, none of that holds. Is reading the same sponsored passage ten times versus once linear, diminishing, or actually more likely to produce a citation? I could not find public research on this, which does not mean none exists, only that it is not widely discussed. Under the dual-track path it has to be answered, or the machine side has reach without frequency and the measurement system is incomplete.

**Can randomization become infrastructure?** The spectrum points at a practical suggestion: problems at the right end respond only to intervention, so build randomization into delivery — hold out a small fraction of traffic by default, continuously generating counterfactuals, rather than designing an experiment each time one is needed. Technically feasible. The cost is revenue on that traffic; the benefit is estimability across the system. Few do it, not because it cannot be done, but because the cost is immediate and the benefit is deferred.

**How should censored data be handled under first-price auctions?** The observation structure corresponds to current status data, for which mature nonparametric estimation theory exists. But the bid shading literature I have read stays with parametric assumptions or censored regression on tree models; the isotonic route is not a main line. There may be good engineering reasons — slower convergence, awkward inference — or the two fields may simply have developed separately. My search was not deep enough to tell, but the question deserves a proper review.

Put together, these point the same way. The first three are new problems from a change in who the audience is. The fourth is an old problem from an end of the spectrum that has not moved in fifteen years. Answering any of them requires not a larger model, but better experimental design and clearer definitions.

---

## Methods

Tested 10 August 2026, 15:07–15:11 UTC, from a US East Coast connection. One machine, one session. For each publisher, the same section page was requested ten times with only the `User-Agent` header varying: Chrome, Safari, Googlebot, Bingbot, ClaudeBot, PerplexityBot, OAI-SearchBot, GPTBot, ChatGPT-User, and bare curl. Response headers and bodies were saved; `robots.txt` and `llms.txt` were fetched once per site for comparison against observed behavior.

Limitations: a single snapshot from a single location; section pages only; User-Agent strings simplified and possibly not matching each vendor's current format; requests not originating from the crawlers' real IP ranges (see the inference above); Reuters returned 401 to all agents and Washington Post produced inconsistent timeouts, so neither yields usable data.

---

## References

**Survey**
- Zhang, W., Yuan, S., & Wang, J. (2016). *Display Advertising with Real-Time Bidding (RTB) and Behavioural Targeting*. [arXiv:1610.03013](https://arxiv.org/pdf/1610.03013)

**User response prediction**
- McMahan, H. B., et al. (2013). *Ad Click Prediction: a View from the Trenches*. KDD 2013. [PDF](https://research.google.com/pubs/archive/41159.pdf)
- He, X., et al. (2014). *Practical Lessons from Predicting Clicks on Ads at Facebook*. ADKDD 2014. [ACM DL](https://dl.acm.org/doi/10.1145/2648584.2648589)
- Chapelle, O. (2014). *Modeling Delayed Feedback in Display Advertising*. KDD 2014. [PDF](http://wnzhang.net/share/rtb-papers/delayed-feedback.pdf)

**Pacing and bidding**
- Agarwal, D., Ghosh, S., Wei, K., & You, S. (2014). *Budget Pacing for Targeted Online Advertisements at LinkedIn*. KDD 2014. [PDF](http://www0.cs.ucl.ac.uk/staff/w.zhang/rtb-papers/linkedin-pacing.pdf) · [ACM DL](https://dl.acm.org/doi/10.1145/2623330.2623366)
- Xu, J., Lee, K.-c., Li, W., Qi, H., & Lu, Q. (2015). *Smart Pacing for Effective Online Ad Campaign Optimization*. KDD 2015. [arXiv:1506.05851](https://arxiv.org/pdf/1506.05851) · [ACM DL](https://dl.acm.org/doi/10.1145/2783258.2788615)
- *A Field Guide for Pacing Budget and ROS Constraints*. [OpenReview](https://openreview.net/pdf?id=HTMFUKAm8B)
- Guo, J., et al. (2024). *Generative Auto-bidding via Conditional Diffusion Modeling*. KDD 2024. [ACM DL](https://dl.acm.org/doi/10.1145/3637528.3671526)
- *Constraint-Aware Generative Auto-bidding via Pareto-Prioritized Regret Optimization*. [arXiv](https://arxiv.org/html/2602.08261)

**Censored data and bid shading**
- Wu, W., Yeh, M.-Y., & Chen, M.-S. (2015). *Predicting Winning Price in Real Time Bidding with Censored Data*. KDD 2015. [ACM DL](https://dl.acm.org/doi/10.1145/2783258.2783276)
- *Bid Shading in The Brave New World of First-Price Auctions*. CIKM 2020. [ACM DL](https://dl.acm.org/doi/10.1145/3340531.3412689)
- *An Efficient Deep Distribution Network for Bid Shading in First-Price Auctions*. [arXiv:2107.06650](https://arxiv.org/pdf/2107.06650)
- *Double Distributionally Robust Bid Shading for First Price Auctions*. [arXiv:2410.14864](https://arxiv.org/pdf/2410.14864)

**Evaluation and simulation**
- Jeunen, O., et al. (2022). *Learning to Bid with AuctionGym*. AdKDD 2022. [PDF](http://papers.adkdd.org/2022/papers/adkdd22-jeunen-learning.pdf)

**Measurement and reach**
- Google Research. *Cross-media measurement with Virtual People*. [Link](https://research.google/pubs/cross-media-measurement-with-virtual-people/)
- Google Research. *Privacy-centric Cross-publisher Reach and Frequency Estimation Via Vector of Counts*. [Link](https://research.google/pubs/pub50153/)
- World Federation of Advertisers. *Private Reach & Frequency Estimators Evaluation Results*. [GitHub](https://github.com/world-federation-of-advertisers/cross_media_measurement_project_site/blob/master/public_papers/PRFE_results/Private%20Reach%20&%20Frequency%20Estimators%20Evaluation%20Results.md)

**Machine audiences and market structure**
- Schmalbach, V. (2026). *TIME Is Serving AI Bots a Different Website, With Ads Built In*. [Link](https://www.vincentschmalbach.com/time-serves-ai-bots-a-different-website/)
- Digiday (2026). *Time has started serving ads to AI agents*. [Link](https://digiday.com/media/time-has-started-serving-ads-to-ai-agents/)
- Sharwood, S. (2026). *'Humans will be a rounding error on the internet' says Cloudflare exec*. The Register, 7 August 2026. [Link](https://www.theregister.com/networks/2026/08/07/humans-will-be-a-rounding-error-on-the-internet-says-cloudflare-exec/5284429)
- Digiday (2026). *Google AI Overviews linked to 25% drop in publisher referral traffic*. [Link](https://digiday.com/media/google-ai-overviews-linked-to-25-drop-in-publisher-referral-traffic-new-data-shows/)
- Search Engine Land (2026). *News publishers expect search traffic to drop 43% by 2029*. [Link](https://searchengineland.com/news-publishers-search-referrals-drop-report-467408)
- Basis. *7 Programmatic Advertising Trends Shaping 2026*. [Link](https://basis.com/blog/7-programmatic-advertising-trends-shaping-2026)
- Adtelligent. *Retail Media Market Outlook 2026*. [Link](https://adtelligent.com/blog/retail-media-market-outlook/)
- Cloudflare. *Introducing pay per crawl*. [Blog](https://blog.cloudflare.com/introducing-pay-per-crawl/)
- TechCrunch (2026). *Cloudflare's new policy pushes AI companies to pay for publishers' content*. [Link](https://techcrunch.com/2026/07/01/cloudflares-new-policy-pushes-ai-companies-to-pay-for-publishers-content/)
- Search Engine Land. *Inside Meta's AI-driven advertising system: How Andromeda and GEM work together*. [Link](https://searchengineland.com/meta-ai-driven-advertising-system-andromeda-gem-468020)
- Ad Context Protocol. [Documentation](https://docs.adcontextprotocol.org/docs/faq)
- IAB Tech Lab. *AAMP — Agentic Advertising Management Protocols*. [Official page](https://iabtechlab.com/standards/aamp-agentic-advertising-management-protocols/)
