# Prompt — Review the Crypto Analyst Team Implementation Plan

_Use this prompt verbatim when asking another LLM (Gemini, Grok, ChatGPT, or another reviewer) to assess the implementation plan. Paste the contents of `IMPLEMENTATION_PLAN.md` immediately after the prompt._

---

## Instructions to the reviewing model

You are reviewing an implementation plan for a multi-agent LLM-driven crypto trading-analysis system called the "Crypto Analyst Team." The plan was synthesized from (a) a system review of the running codebase plus four weeks of paper-trading database history, and (b) three independent prior LLM analyses of that review. Your job is to give the plan an *honest critical assessment* — not validation.

### Background you need

The system runs an 11-persona LLM analyst panel (ARIA, MARCUS, NOVA, VEGA, DELTA, CHAIN, QUANT, DEFI, ATLAS, REX, ZEN) on a 4-hour cron over BTC, ETH, and RPL. Signals are persisted to a SQLite database and rendered on a Streamlit dashboard. Portfolio is a $124,000 paper account.

After 28 days (706 closed trades) the system shows:
- Realized P&L: +$188 (37% win rate, avg trade −0.19%)
- BTC trades: +$10,220; ETH trades: −$9,671 (the BTC gain almost exactly offsets the ETH loss)
- One orphan SOL SHORT at unrealized −$1,369 / −74%
- Last 7 days: −$4,904 at 24% win rate (deteriorating)

Two weekly lookbacks identified the dominant failure modes as (i) 11 analysts piling into one direction acting as one concentrated bet, (ii) trend-continuation in mid-range as the worst trade pattern, (iii) REX trading the team's own book under "balancing" framing, and (iv) ZEN's contrarian fades losing on vibes. A first round of guardrails (`guardrails-v1`) was added after the 4/20 lookback but has only one production run as of this plan.

### What I want from your review

Your review will be compared side-by-side with reviews from other LLMs, so I am specifically looking for *what you contribute that the others might miss*. Generic agreement with the plan is not useful. Be concrete and willing to disagree.

Structure your response in these six sections, in this order, with these exact headings:

#### 1. Single-sentence verdict
One sentence: is this plan likely to materially improve the system, or not? Pick a side.

#### 2. Impact ordering — what's wrong
The plan orders items #1 through #11 by estimated impact. Identify any item that is in the wrong slot. Explain *why* you'd move it, with reasoning grounded in the data above. If you think the ordering is roughly right, say so explicitly and explain why — don't dodge the question.

#### 3. What's missing
Name up to three specific changes that are *not* in the plan but should be. For each:
- What it is in concrete technical terms
- Why it would matter more than at least one of the items currently in the plan
- Which existing item it would displace

If you cannot name three, name fewer rather than padding. "Nothing missing" is a valid answer if you genuinely believe it.

#### 4. What should be removed or downgraded
Name any item in the plan that you believe is *not worth the effort* or whose impact is overestimated. Be specific about which item and why. Particularly scrutinize items #2 (regime-aware prompting), #9 (calibration-weighted sizing), and #10 (analyst panel consolidation) — those are the three highest-effort items, and high effort with low payoff is the most expensive kind of mistake here.

#### 5. Risks the plan does not address
Identify operational, statistical, or methodological risks the plan glosses over. Examples of the *kind* of risk to consider (not an exhaustive list): regime shifts during the 4-week observation window invalidating the data, survivorship bias in the calibration tracking, coupling between guardrails masking which one is actually working, false confidence from a 28-day sample size, dashboard-driven optimization (Goodhart's Law on the win-rate target).

For each risk: how likely is it, and what would mitigate it?

#### 6. Confidence calibration on your own assessment
On a 1-10 scale, how confident are you in this review's conclusions? What evidence would change your mind in either direction? Be honest — "high confidence in the diagnosis, low confidence in the precise reordering" is a valid and useful answer.

### Constraints on your response

- Maximum length: 1,200 words across all six sections. Brevity is rewarded.
- Do not restate the plan back to me. I wrote it; I know what it says.
- Do not hedge. Pick positions and defend them. "It depends" without specifics is not an answer.
- Do not invoke "best practices" without naming the specific failure mode you're protecting against.
- Cite specific items by number (#1, #5, #10, etc.) when referencing the plan — this lets me cross-compare reviews.
- If you genuinely have nothing critical to add to a section, write "No substantive disagreement" for that section and move on. That is more useful than padded agreement.

### What "good" looks like

A useful review has at least one of:
- A reordering argument I find persuasive enough to actually swap items
- A missing change that I add to the plan after reading
- A risk I had not considered, with a concrete mitigation
- A specific reason to drop or de-prioritize one of the higher-effort items

A review that produces none of these has not earned my time.

---

## The plan to review

[PASTE THE CONTENTS OF `IMPLEMENTATION_PLAN.md` HERE]
