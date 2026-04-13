# Crypto Analyst Team — Full Agent Team Review

**Date**: 2026-04-06  
**Reviewed by**: Security Engineer, Contrarian Reviewer, Code Auditor, QA Tech, Docs Checker  
**Codebase**: 8 source files (2,830 lines) + 1,316-line dashboard + 4 test files (29.7K)

---

## Project Overview

A multi-agent AI trading analysis system with 5 distinct analyst personalities (ARIA, MARCUS, NOVA, REX, ZEN), each powered by Claude via the Anthropic SDK. Features:
- Rich terminal chat interface with slash commands
- Live market data from CoinGecko, Binance, yfinance, Alternative.me
- Automatic signal parsing and position tracking (SQLite)
- Auto-close on target/stop-loss hits
- Lookback memory for lessons-learned injection
- 1,316-line Streamlit dashboard
- 31 supported coins

### Architecture

```
main.py (chat loop, commands, signal parsing)
  ├── agents.py (5 analyst agents, prompt construction, API calls)
  ├── data_fetcher.py (CoinGecko, Binance, yfinance, RSS news)
  ├── indicators.py (RSI, MACD, BB, EMA, ATR, StochRSI, VWAP, pivots)
  ├── tracker.py (SQLite DB: recommendations, positions, lookback memory)
  ├── performance.py (P&L reporting, lookback report generation)
  ├── config.py (shared constants, coin mappings)
  └── dashboard.py (Streamlit web dashboard)
```

---

## 1. SECURITY ENGINEER

### Result: PASS (no critical issues)

| Severity | Finding |
|----------|---------|
| CLEAR | No hardcoded API keys or secrets in source code |
| CLEAR | No `eval()`, `exec()`, `os.system()`, `pickle.loads()` |
| CLEAR | All SQL uses parameterized queries — no injection risk |
| POSITIVE | Prompt injection defense via `_sanitise_memory()` in `agents.py:336-371` — blocks known injection patterns, strips control chars, caps memory at 2000 chars |
| INFO | `.env` file exists with real API key but is separate from source |
| LOW | No `.gitignore` found — risk of committing `.env` with secrets |
| LOW | `_sanitise_memory` regex is line-start-only (`^`), which could be bypassed with leading whitespace + injection phrase |

### Previous CODE_REVIEW.md Issues (status check)

The prior code review (2026-04-02) flagged:
- **HIGH: Prompt injection via lookback memory** — NOW FIXED via `_sanitise_memory()`
- **MEDIUM: Hardcoded DB paths** — NOW FIXED (uses `config.DB_PATH`)

---

## 2. CONTRARIAN REVIEWER

### Result: 17 concerns

#### Oversized Functions (15 functions exceed 50-line limit)

| File | Function | Lines | Severity |
|------|----------|-------|----------|
| `agents.py` | `format_market_data_for_prompt()` | ~204 | HIGH — largest function in codebase |
| `main.py` | `main()` | ~123 | MEDIUM |
| `main.py` | `run_general_query()` | ~90 | MEDIUM |
| `main.py` | `handle_close_intent()` | ~89 | MEDIUM |
| `indicators.py` | `calculate_all_indicators()` | ~117 | HIGH |
| `tracker.py` | `check_and_close_positions()` | ~89 | MEDIUM |
| `performance.py` | `generate_lookback_report()` | ~73 | LOW |
| `performance.py` | `update_open_recommendations()` | ~72 | LOW |
| `performance.py` | `generate_performance_report()` | ~68 | LOW |
| `main.py` | `parse_signal()` | ~68 | LOW |
| `data_fetcher.py` | `fetch_all_market_data()` | ~68 | LOW |
| `data_fetcher.py` | `fetch_crypto_news()` | ~64 | LOW |
| `tracker.py` | `init_db()` | ~62 | LOW |
| `agents.py` | `_build_system_prompt()` | ~81 | MEDIUM |
| `main.py` | `show_history()` | ~51 | LOW |

#### False-positive TODOs

The contrarian flagged 3 "TODO" markers, but inspection shows these are NOT actual TODO comments — they're inside string literals (analyst prompt text containing examples like `"SIZE: 2.1% ($2,604)"`). The word detection is a false positive from the word "fall" matching in sentiment word lists. **No actual TODOs in committed code.**

---

## 3. CODE AUDITOR

### File Metrics

| File | Lines | Status | Long Lines |
|------|-------|--------|------------|
| `main.py` | 799 | FLAG (>500) | 0 |
| `agents.py` | 624 | FLAG (>500) | 2 |
| `config.py` | 53 | OK | 0 |
| `data_fetcher.py` | 420 | OK | 0 |
| `indicators.py` | 260 | OK | 0 |
| `tracker.py` | 434 | OK | 1 |
| `performance.py` | 240 | OK | 0 |
| `dashboard.py` | 1,316 | FLAG (>>500) | many |
| **Total** | **4,146** | | **4** |

### Code Quality

- **Exception handling**: All files use `except Exception` (not bare `except:`) — compliant, but overly broad in several places where specific exceptions should be caught
- **SQL safety**: All parameterized — clean
- **No circular imports**: Module dependency graph is clean
- **dashboard.py duplicates logic**: Makes its own `sqlite3` and `requests` calls instead of reusing `tracker.py` and `data_fetcher.py` — maintenance risk

### Architecture Concerns

1. **Global mutable state**: `main.py` uses module-level `_session` dict and `agents.py` uses module-level `MODEL` constant. The `es` global in the cntag review was worse, but these are still not ideal.
2. **`dashboard.py` at 1,316 lines**: This is the largest file by far and duplicates DB access, API calls, and formatting logic from other modules.
3. **Single-retry rate limit**: `agents.py:602-606` waits 60s and retries once on rate limit. With 5 analysts running sequentially, a rate limit could cause 5 × 60s = 5 minutes of blocking.

---

## 4. QA TECH

### Test Results: 74 passed, 3 failed (77 total)

```
tests/test_data_fetcher.py     17 passed
tests/test_indicators.py       18 passed
tests/test_tracker.py          16 passed
tests/test_round2.py           23 passed, 3 failed
```

### 3 Failing Tests

All in `test_round2.py::TestFetchCryptoNews`:
- `test_returns_empty_list_on_network_error`
- `test_returns_empty_list_on_malformed_response`
- `test_headline_structure`

**Root cause**: Tests mock `data_fetcher._get()` but `fetch_crypto_news()` has an RSS fallback path that bypasses `_get()`, fetching live data instead. The mocks don't isolate all network paths.

### Test Coverage Gaps

| Module | Coverage | Gap |
|--------|----------|-----|
| `agents.py` | Partial (injection regex only) | Core agent orchestration, prompt construction, API call flow untested |
| `performance.py` | NONE | Lookback memory, performance reports untested |
| `main.py` | Partial (signal parser only) | Chat loop, multi-coin fetch, close intent, command handling untested |
| `dashboard.py` | Minimal (SQL check only) | Streamlit rendering, chart generation untested |
| `config.py` | Cross-checked only | No dedicated tests |

### What IS Well-Tested

- **indicators.py**: Comprehensive coverage — RSI range, MACD identity, BB ordering, VWAP reset, edge cases
- **tracker.py**: Full CRUD cycle — save, close, history, stats, confidence clamping
- **data_fetcher.py**: Order book imbalance math, CoinGecko ID mapping, rate limit handling
- **Signal parsing**: LONG/SHORT persistence, WATCH/NEUTRAL exclusion, missing fields

---

## 5. DOCS CHECKER

| Document | Status |
|----------|--------|
| `README.md` | EXISTS (20K — comprehensive) |
| `CODE_REVIEW.md` | EXISTS (20K — prior review) |
| `CHANGELOG.md` | **MISSING** |
| `requirements.txt` | EXISTS |
| `.env.example` | EXISTS |
| `docs/API.md` | MISSING (empty `docs/` dir) |
| `docs/ARCHITECTURE.md` | MISSING |

The README is thorough (covers installation, architecture, DB schema, all commands, supported coins, data sources). The main gaps are operational docs — no CHANGELOG, no API docs, no deployment guide for the dashboard.

---

## Summary by Severity

| Severity | Count | Key Items |
|----------|-------|-----------|
| **HIGH** | 2 | `format_market_data_for_prompt()` at 204 lines, `calculate_all_indicators()` at 117 lines |
| **MEDIUM** | 8 | 3 failing tests (mock isolation), 5 functions 80-123 lines, dashboard duplicates module logic, 2 source files >500 lines |
| **LOW** | 10 | 8 functions 51-73 lines, no `.gitignore`, sanitize regex bypassable with leading whitespace |
| **POSITIVE** | 5 | No hardcoded secrets, SQL injection safe, prompt injection defense, comprehensive README, well-tested core modules |
| **MISSING** | 3 | CHANGELOG, docs/API.md, docs/ARCHITECTURE.md |

### Top 5 Action Items

1. **Fix 3 failing news tests** — mock the RSS fallback path in addition to `_get()`
2. **Add tests for `agents.py` and `performance.py`** — the two largest untested modules
3. **Refactor `format_market_data_for_prompt()`** (204 lines) — break into per-section helper functions
4. **Refactor `calculate_all_indicators()`** (117 lines) — extract indicator groups into sub-functions
5. **Stop `dashboard.py` from duplicating** `tracker.py` and `data_fetcher.py` logic — import and reuse

### Production Readiness Assessment

The core trading logic is **solid** — parameterized SQL, prompt injection defense, proper error handling, signal parsing with validation, auto-close with P&L tracking. The main risks are operational: test gaps in agent orchestration, large functions that are hard to maintain, and the dashboard's duplicated logic. For a research/personal tool, this is production-quality. For a team product, the test coverage and refactoring items above should be addressed.
