<!--
Thanks for the PR. Before merging, walk through this checklist. Delete sections that don't apply.
-->

## What this change does

<!-- One or two sentences. Why this change exists, not how. -->

## Linked ADR / issue

<!-- e.g. Implements ADR-0003. Closes #14. If this change is architecturally significant and has no ADR, open one before merging. -->

## Checklist

- [ ] Tests added or updated (or explicitly justified not)
- [ ] If this change touches features: leakage check — no feature uses information unavailable at the target timestamp
- [ ] If this change touches models: calibration and reproducibility tests pass
- [ ] If this change touches bet selection or sizing: no hardcoded sizes; all thresholds are configurable
- [ ] If this change touches the silver schema: sport-agnostic (no `nhl_` anywhere; `sport_id` carries the distinction)
- [ ] If this change introduces a new tool, vendor, or data source: ADR written
- [ ] Secrets scan clean (no API keys, tokens, or odds snapshots with PII)
- [ ] Docs updated (CLAUDE.md, architecture, or data-sources.md as relevant)

## Notes for the reviewer

<!-- Anything subtle, surprising, or worth a second pair of eyes. Be honest about what you're unsure of. -->
