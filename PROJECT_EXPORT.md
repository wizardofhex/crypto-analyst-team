# Cowork Project Export — crypto-analyst-team

This document captures everything needed to recreate the `crypto-analyst-team`
Cowork project (folders, instructions, scheduled tasks, connectors, and files).
To import: create a new Cowork project, then follow the sections below in order.

---

## 1. Project Metadata

| Field | Value |
|-------|-------|
| Project name | `crypto-analyst-team` |
| Source repo | https://github.com/wizardofhex/crypto-analyst-team |
| Primary user | Bill (bill.burns@diskoverdata.com) |
| Default model for scheduled runs | `claude-opus-4-7` |

---

## 2. Folders to Mount

In the new Cowork project, mount this folder (use "Select folder" in the
Cowork UI). It should point at a local working checkout of the repo.

| Mount label | Example local path | Required |
|-------------|--------------------|----------|
| `crypto-analyst-team` | `G:\My Drive\Development\AI Agents\AI Agent Team\crypto_analyst_team` | **Yes** |

### One-time setup on the user's machine
```bash
git clone https://github.com/wizardofhex/crypto-analyst-team.git
cd crypto-analyst-team
# create .env with ANTHROPIC_API_KEY=sk-ant-...
pip install -r requirements.txt
gh auth login && gh auth setup-git
```

---

## 3. Project Instructions (paste into Cowork → Project → Instructions)

The CLAUDE.md is now in the repo at wizardofhex/crypto-analyst-team.
When you create a project in Claude Cowork and point it to this repo, it will
automatically pick up the CLAUDE.md as project context. It covers:
- All 11 analysts and their roles
- Architecture and deployment setup
- How to run scheduled and interactive analysis
- Data sources and cost estimates
- How to add new analysts or coins
- Signal format and database schema
- Environment variables needed
Follow these instructions when working in this project.

---

## 4. Connectors / MCPs to Enable

- Google Calendar, Gmail, Google Drive, Slack
- Claude in Chrome
- Everything Search
- Scheduled Tasks, MCP Registry, Plugins, Session Info

Only project-specific secret is the `.env` file inside the repo folder.

---

## 5. Scheduled Tasks

### 5.1 crypto-4h-analysis
- Cron: `0 */4 * * *`
- Cmd:  `run_scheduled_analysis.py BTC ETH RPL --push --model claude-opus-4-7`
- Cost: ~$125/month on Opus 4.7 (≈5× Sonnet pricing — verify against current Anthropic per-token rates)

### 5.2 crypto-weekly-lookback
- Cron: `0 23 * * 0`
- Cmd:  `run_weekly_lookback.py BTC ETH RPL --days 7 --push --model claude-opus-4-7`
- Cost: ~$0.25/week on Opus 4.7

---

## 6. Files in the Workspace Folder

| File | Tracked? | Purpose |
|------|----------|---------|
| SCHEDULING_SETUP.md | untracked — commit | Scheduling docs |
| run_weekly_lookback.py | untracked — commit | Weekly lookback runner |
| historical_analysis_*.md | output | Regenerable |
| recommendations.db | tracked | SQLite store |
| recommendations.db-journal | no | Transient |
| .env | **no** (git-ignored) | API keys — recreate locally |

---

## 7. Import Checklist

- [ ] Create new Cowork project named `crypto-analyst-team`
- [ ] Clone the GitHub repo locally
- [ ] Mount that folder in Cowork
- [ ] Create `.env` with `ANTHROPIC_API_KEY`
- [ ] `pip install -r requirements.txt`
- [ ] Paste project instructions from §3
- [ ] Enable connectors from §4
- [ ] Recreate scheduled tasks from §5
- [ ] Verify `g