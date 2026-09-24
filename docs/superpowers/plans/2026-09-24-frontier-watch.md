# Frontier Watch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a daily DSP/FPGA/embedded digest that can reach a phone.

**Architecture:** Python standard-library collectors normalize RSS and GitHub data into one entry type. A curator filters, ranks and deduplicates entries; a runner formats one digest, sends through a configured HTTPS channel, and persists sent IDs only after success. GitHub Actions supplies a daily hosted schedule.

**Tech Stack:** Python 3.11+, standard library, `unittest`, GitHub Actions.

**Spec:** `docs/spec.md`

## Global Constraints

- Credentials are environment variables or GitHub Secrets, never repository content.
- Dry runs have no push or state side effects.
- Source errors may be partial; all source failures block sending.
- The first release requires no paid AI API or third-party Python package.

## Review Focus

- Missing or malformed publication dates: handle safely without sending stale content as fresh.
- A duplicate item from two feeds: send once and record one stable ID.
- Push HTTP success with application-level error: leave the item unsent and report failure.
- RSS namespace variations and HTML in summaries: parse safely into readable text.
- A missing token or wrong channel: fail before attempting delivery and keep state intact.

---

### Task 1: Curate entries

**Files:** Create `frontier_watch/models.py`, `frontier_watch/curate.py`, `tests/test_curate.py`.

**Interfaces:** `Entry(id, title, url, source, published, summary, kind)` and `CuratedEntry(entry, topic, score)`; `select_entries(entries, seen_ids, now, lookback_hours, limit) -> list[CuratedEntry]`.

- [x] Write tests for topic matching, irrelevant entries, age boundary, duplicate IDs/URLs, ordering, and limit; run `python -m unittest tests.test_curate -v` and observe the expected missing-module failure.
- [x] Implement the two dataclasses and curator until the focused test passes.
- [x] Run `python -m unittest discover -s tests -v` and inspect all results.

### Task 2: Collect public sources

**Files:** Create `frontier_watch/sources.py`, `tests/test_sources.py`.

**Interfaces:** `fetch_all(now, http_get, github_token=None) -> (list[Entry], list[str])`; HTTP responses are bounded bytes and failures are per source.

- [x] Write fixture-driven tests for RSS 1.0/2.0, GitHub JSON, dates and partial failure; run `python -m unittest tests.test_sources -v` and observe failure.
- [x] Implement one arXiv RSS request, verified news RSS requests, and three GitHub topic searches using URLs and official rate limits; make focused tests pass.
- [x] Run the complete unittest suite.

### Task 3: Send digest and preserve state

**Files:** Create `frontier_watch/delivery.py`, `frontier_watch/app.py`, `frontier_watch/__main__.py`, `tests/test_delivery.py`, `tests/test_app.py`.

**Interfaces:** `format_digest(entries, now) -> str`; `send_digest(text, channel, env, http_post)` raises `DeliveryError` on failure; `run(now, dry_run, ...)` coordinates retrieval, curation, push and state.

- [x] Write tests for one digest, channel payloads, credential checks, dry run, empty result, and state write only after successful delivery; run focused tests and observe failure.
- [x] Implement the formatter, HTTP delivery and runner; make focused tests pass.
- [x] Run the complete unittest suite and a dry-run command.

### Task 4: Daily deployment and handoff

**Files:** Create `.github/workflows/digest.yml`, `.gitignore`, `README.md`, `examples/sample.json`, `examples/topics.json`, `scripts/install_windows.ps1`, `scripts/run_windows.ps1`, `tests/test_windows_runner.py`.

**Interfaces:** `python -m frontier_watch --dry-run` for preview; `python -m frontier_watch` for push; GitHub Actions runs daily and commits `data/sent.json` only when changed.

- [x] Add a sample mode whose expected output can be checked offline, then verify it from the command line.
- [x] Add workflow with daily UTC cron corresponding to China morning, permissions for state commit, and repository secrets; verify YAML structure and runtime command locally where possible.
- [x] Write Chinese deployment instructions for GitHub Actions and Windows Task Scheduler, implement DPAPI-backed local setup, and link the verified original projects.
- [x] Run full tests, syntax compilation, offline sample, and Git status inspection; report external push validation as pending credentials if none exist.
