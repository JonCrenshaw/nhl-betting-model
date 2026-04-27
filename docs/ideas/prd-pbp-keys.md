# PR-D play-by-play key scan — placeholder

PR-D's first task, before any parser code, is to scan
`plays[*].details` keys per `typeDescKey` against the spike's saved
play-by-play Parquet (`local-cache/spike/pra-one-game/play-by-play.parquet`)
or a fresh single-game fetch. Goal: confirm the canonical keys per
event type so the loader's pydantic schema doesn't ossify around
fields that turn out to be inconsistent across event types.

Specifically, per [PR-A spike notes §5](./pra-spike-notes.md):

- `xCoord` / `yCoord` should be present on shooting events
  (`shot-on-goal`, `goal`, `missed-shot`, `blocked-shot`).
- `eventOwnerTeamId` / `losingPlayerId` + `winningPlayerId` (or the
  current equivalents) should be present on faceoffs.
- `plays[0]` is structural — period-start type with no `details`
  block. Skip rather than skip-with-warning.

When the scan runs, drop its output here under headings per
`typeDescKey`, capturing the union of keys observed and any nullable
fields. This file becomes a parser-design input and a witness against
future API drift; PR-H absorbs it into ADR-0003 alongside
[`pra-spike-notes.md`](./pra-spike-notes.md), then deletes both.

## Scan output

*To be populated by PR-D's first task.*
