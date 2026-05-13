# Now

The current state of work on PuckBunny. Updated by Claude at the end of every session.

This is the fastest way for a fresh Claude session to learn where we left off. It is read at the top of every session as part of the startup checklist in `CLAUDE.md`.

Keep this file under ~80 lines. If it grows beyond that, content has either gone stale or belongs in `docs/roadmap.md`, an ADR, or a `docs/ideas/` file.

---

## Active branch / PR

- Branch: to-be-created `feat/m2-pr-h-adr-0003` (PR-H edits currently sit unstaged on whatever branch Windows has checked out — Jon to create the branch in GitHub Desktop before committing). PR-G was pushed during the prior session; PR-H is the milestone-close PR for M2.
- Open PR: none yet for PR-H (drafted locally, awaiting commit + push). PR-G PR status: confirm in GitHub before opening PR-H against `main`.

## Currently in flight

- M2 PR-H: ADR-0003 + warehouse doc refresh + R2 runbook + spike-file deletions — all edits drafted on disk, awaiting commit on `feat/m2-pr-h-adr-0003`, push, and PR open against `main`. When this PR merges, M2 closes — cue the `docs/efficiency.md` milestone-close review.

## Last session summary

- M2 PR-H drafted locally. New files: `docs/decisions/0003-nhl-api-surface-and-bronze-shape.md` (Accepted; captures D1–D12 with revisit triggers — D1–D7 from PR-A/B planning, D8–D11 from PR-G backfill/cost-check/dedupe, D12 from the PR-F0 spike's `gameTypeId` decision; ~225 lines, decision-sentence + revisit-trigger format per option C "tight ADR") and `docs/infrastructure/r2.md` (permanent runbook covering provisioning, smoke tests, layout, cost posture, token rotation, troubleshooting — lifted from the M2 milestone doc's kickoff prerequisites section). Refreshed `docs/architecture/data-warehouse.md` (status flipped from "Not yet implemented" to "Bronze layer implemented as of M2"; bronze tree reconciled to hyphenated partition slugs `skater-summary`/`goalie-summary`/`team-summary` and adds `club-schedule-season`; ADR-0003 added to the decision-record header alongside ADR-0001). Refreshed `docs/milestones/m2-nhl-ingestion.md` (status line "PR-A through PR-G merged, PR-H in flight"; architecture-diagram tree updated to as-built `src/puckbunny/...` — `roster.py` → `team_season.py`, plus `season_summaries.py`/`backfill.py`/`cost_check.py`/`storage/base.py`/`storage/local.py` and the `tests/` tree; PR-A and PR-D bullets re-pointed at ADR-0003 in place of the deleted spike files; PR-H bullet rewritten to describe what shipped; R2 bucket-provisioning section collapsed to a one-line pointer to `docs/infrastructure/r2.md`). Updated indexes: `docs/decisions/README.md` now lists ADR-0002 and ADR-0003; `docs/ideas/README.md` drops the `prd-pbp-keys.md` entry. Deleted `docs/ideas/pra-spike-notes.md` and `docs/ideas/prd-pbp-keys.md` (the second was a scope expansion vs the literal M2-doc PR-H bullet, justified by the file's self-described deletion-in-PR-H and the ideas README's matching note; Jon confirmed mid-session). Inbound-reference repairs so no live link points at a deleted file: `src/puckbunny/storage/parquet.py` and `src/puckbunny/ingestion/nhl/schemas.py` docstrings re-pointed to ADR-0003 D3/D10; `tests/ingestion/fixtures/games/README.md` ditto; `docs/ideas/prf-stats-rest-spike-notes.md` repaired. The remaining `tools/spike/prf_stats_rest_probe.py` line-18 attribution to "pra-spike-notes §Open questions" left intact as a historical citation — not a link. Test sanity check (`pytest -q` on the two docstring-edited modules) blocked by the Linux sandbox's inability to download a fresh `uv` Python build; runtime risk is zero (docstrings only) but worth a `uv run pytest -q` on Windows before push.

## Blocked

- _(none)_

## Next concrete step

- In GitHub Desktop: create `feat/m2-pr-h-adr-0003` off `main`, commit the PR-H edits, push, open PR against `main`. Suggested PR title: `docs(m2): ADR-0003 + warehouse refresh + R2 runbook (M2 PR-H)`. PR description should call out (a) the deletion of two spike-notes idea files now absorbed into ADR-0003, (b) D12 as a new decision surfaced by the PR-F0 spike (vs the M2 doc's literal D1–D11 framing), and (c) that this is the milestone-close PR, so its merge should cue the `docs/efficiency.md` review per CLAUDE.md. Run `uv run pytest -q` on Windows once before push as a defensive check on the two docstring edits (`parquet.py`, `schemas.py`).

---

## How this file is maintained

Claude updates this file as part of the end-of-session summary, every session, without being asked. The `/wrap` slash command in `.claude/commands/` is the canonical trigger.

Update rules:

- **Replace, don't append.** This file is current state, not a log. Git history is the log.
- One-line entries where possible; link to the relevant doc, ADR, or PR for detail.
- **If the session produced nothing substantive (no code changes, no new ADR, no doc landings), leave "Last session summary" as-is.** The most recent substantive summary should persist so a fresh session still sees the last meaningful context. Other fields ("Currently in flight," "Next concrete step," "Blocked") can still be updated if those facts changed during the session — e.g., a planning conversation might sharpen the next step or surface a new blocker without producing any code.
- If the active branch is `main`, leave "Open PR" as "none" rather than removing the line.
- The "Efficiency reviews" cadence in `docs/efficiency.md` may append a short review note at the bottom of this file at milestone close. Those notes age out — clear them when the next milestone closes.
