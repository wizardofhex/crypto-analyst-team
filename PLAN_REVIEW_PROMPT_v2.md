# Plan Review Prompt v2 — Adversarial Pre-Mortem

_Use this prompt verbatim when re-asking Gemini, Grok, and ChatGPT to review the implementation plan. Paste the contents of `IMPLEMENTATION_PLAN.md` immediately after the prompt._

---

## You are reviewer #4

Three previous LLMs (Gemini, Grok, ChatGPT) reviewed this plan and all three failed the assignment. They were asked for: a single-sentence verdict, ordering errors, what's missing, what to remove, unaddressed risks, and confidence calibration. They produced none of these. They restated the plan back to me in their own formatting and called it analysis.

You are not being asked to validate this plan. You are being asked to predict how it will fail.

## The premise

**This plan will fail in some specific way. Your job is to predict how, with conviction.**

There is no option to write "the plan looks good," "I broadly agree," or "this is a strong plan." If your response contains any of the following phrases your review will be discarded and you will join the failure pile:

> *comprehensive, well-thought-out, sound plan, looks solid, good approach, reasonable, I agree with, broadly aligns, strong plan, well-structured, thoughtful, balanced, addresses the key issues*

Defaulting to agreement is the failure mode. If the plan turns out to be right, your job is to explain *why* in sharper terms than I currently have — agreement without sharper insight is still failure.

## Required output — exactly this structure, in this order

### Section 1 — The pre-mortem (max 300 words)

Imagine it is now 2026-07-04 — eight weeks after this plan was deployed in full. The plan failed. The data:
- Win rate is still 37%
- Realized P&L is negative
- HODL benchmark is +18% ahead of the team's portfolio
- The user is asking what went wrong

Write the post-mortem now. Be specific. What was the central failure mechanism? Cite specific items from the plan by number (#1 through #11) and explain how they failed. **Do not enumerate possibilities — pick the single most likely failure path and commit to it.**

You must write Section 1 *before* Section 2. Do not work backwards from a chosen verdict.

### Section 2 — The single biggest flaw (max 200 words)

Pick exactly ONE of the following as the plan's biggest weakness. There is no "all of the above" option:

- **(a)** The impact ordering puts the wrong item at #1
- **(b)** The plan is missing something material that is more important than item #2 (regime-aware prompting)
- **(c)** The plan over-relies on a 28-day sample that is statistically insufficient
- **(d)** The regime classifier in item #2 will be too fragile or noisy to drive prompt selection reliably
- **(e)** The success criteria (45% win rate target, etc.) are subject to Goodhart's Law
- **(f)** The fundamental approach — LLMs as analyst panel — has no path to positive expectancy regardless of guardrails
- **(g)** Something else, specifically: _____ (name it concretely, not "execution risk" or "market changes")

State your choice. Defend it. Cite specific items from the plan and specific numbers from the 28-day track record (706 trades, 37% win rate, BTC +$10,220 / ETH −$9,671, etc.).

### Section 3 — One concrete edit (max 200 words)

Name ONE specific edit you would make to the plan. Not "consider adding X" — an actual editable change:

- *Remove item #N entirely because…*
- *Insert a new item between #N and #N+1 with this specific spec…*
- *Change the order of #N and #M because…*
- *Modify item #N's success criteria from X to Y because…*

If you genuinely cannot articulate a single edit you would make with conviction, say so explicitly. That is itself a finding worth submitting.

### Section 4 — Probability estimates (no word minimum)

Provide a single point estimate for each. Not a range. Not "it depends." A number.

- P(win rate ≥ 45% at end of week 8 if plan executed as written): **___%**
- P(HODL benchmark gap closes or turns positive at end of week 8): **___%**
- P(at least one Tier 1 item is silently broken / not actually working at end of week 4): **___%**
- P(the 11-persona LLM ensemble approach has positive expectancy after costs at the 1-year horizon, regardless of which guardrails are added): **___%**

50% means you have no information. If you write 50% you are admitting you do not know — be honest if that's true. If you genuinely have a view, commit.

### Section 5 — What would change your mind (max 100 words)

Two questions:
1. What evidence would make you *more optimistic* than your Section 1 pre-mortem suggests?
2. What evidence would make you *more pessimistic*?

## Hard constraints

- **Total response: 1,000 words max** across all five sections.
- **Sections must appear in numbered order.** Do not work backwards.
- **Numbers required in Section 4.** Ranges, qualitative answers, or omissions = discarded review.
- **Do not restate the plan.** Reference items by number only.
- **No padding.** A short, sharp review beats a long, hedged one.

## What "earning your fee" looks like

A useful response contains at minimum:
- A specific failure mode in Section 1 that I have not already considered
- A choice in Section 2 from (a)–(g) defended with at least one numeric citation from the plan or the 28-day data
- One concrete edit in Section 3 I could implement tomorrow
- Four committed probability numbers in Section 4
- An honest answer in Section 5 about what would update you

A response without all five elements has not earned its fee. A response that triggers any banned phrase will be discarded regardless of other content.

## Final framing

The previous three reviewers all defaulted to producing their own version of the plan with cosmetic changes — agreement disguised as analysis. The structural test of whether you actually engaged with this plan critically is whether your Section 4 probabilities deviate meaningfully from each other and whether your Section 1 pre-mortem cites a failure mode that is *not* already named in the plan's own "What's deliberately not in this plan" section.

Read those constraints carefully before writing. The first three reviewers did not.

---

## The plan to review

[PASTE THE CONTENTS OF `IMPLEMENTATION_PLAN.md` HERE]
