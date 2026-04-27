# PR-D play-by-play key scan

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

**Source.** `local-cache/spike/pra-one-game/play-by-play.parquet`,
written by the PR-A spike on 2026-04-25. Game `2025030123` (TBL @ MTL,
playoff opener, `gameType=3`, `gameState=OFF`). 319 plays, 13
distinct `typeDescKey` values.

**Run command.** `python tools/spike/scan_pbp_keys.py` (one-off,
not committed). Output reproduced below verbatim.

### Top-level response keys

```
['awayTeam', 'clock', 'displayPeriod', 'easternUTCOffset', 'gameDate',
 'gameOutcome', 'gameScheduleState', 'gameState', 'gameType',
 'homeTeam', 'id', 'limitedScoring', 'otInUse', 'periodDescriptor',
 'plays', 'regPeriods', 'rosterSpots', 'season', 'shootoutInUse',
 'startTimeUTC', 'summary', 'tvBroadcasts', 'venue', 'venueLocation',
 'venueUTCOffset']
```

`plays` (319 entries) and `rosterSpots` (40 entries; one per dressed
skater + goalie across both teams) are the two collection-shaped
fields. Spike-§3 already noted `rosterSpots` lives here, not on
boxscore — confirmed.

### plays[*] top-level keys

Every play carries the same nine structural keys — `eventId`,
`homeTeamDefendingSide`, `periodDescriptor`, `situationCode`,
`sortOrder`, `timeInPeriod`, `timeRemaining`, `typeCode`,
`typeDescKey` — at 319/319.

Two optional keys at the top level:

- `details` — 310/319. Missing only on the 9 structural events listed
  below.
- `pptReplayUrl` — 5/319. Appears only on `goal` events. Marketing
  asset, not modeling-relevant.

### Events with no `details` block

| `typeDescKey` | count |
|---------------|------:|
| `period-start` | 4 |
| `period-end`   | 4 |
| `game-end`     | 1 |

Spike notes §5 only flagged `plays[0]` (period-start) — confirmed
that `period-end` and `game-end` also lack `details`. **Parser
implication:** treat `details is None` as legitimate for these three
`typeDescKey` values; raise on missing `details` for any other
`typeDescKey`.

(The four `period-start` rows correspond to regulation periods 1–3
plus one OT. `regPeriods=3`, `otInUse=true` in the response. The OT
period-start has its own row.)

### `details` keys per `typeDescKey`

`n` is the count of plays with that `typeDescKey`; numbers are
"present / total". 100% means present on every row.

#### `shot-on-goal` (n=41)

| key | present |
|-----|--------:|
| `awaySOG` | 41/41 |
| `eventOwnerTeamId` | 41/41 |
| `goalieInNetId` | 41/41 |
| `homeSOG` | 41/41 |
| `shootingPlayerId` | 41/41 |
| `shotType` | 41/41 |
| `xCoord` | 41/41 |
| `yCoord` | 41/41 |
| `zoneCode` | 41/41 |

#### `goal` (n=5)

| key | present |
|-----|--------:|
| `awayScore` | 5/5 |
| `eventOwnerTeamId` | 5/5 |
| `goalieInNetId` | 5/5 |
| `homeScore` | 5/5 |
| `scoringPlayerId` | 5/5 |
| `scoringPlayerTotal` | 5/5 |
| `shotType` | 5/5 |
| `xCoord` | 5/5 |
| `yCoord` | 5/5 |
| `zoneCode` | 5/5 |
| `discreteClip` / `highlightClip` / `*Fr` / `highlightClipSharingUrl` (six clip-asset fields) | 5/5 |
| `assist1PlayerId` | 4/5 |
| `assist1PlayerTotal` | 4/5 |
| `assist2PlayerId` | 3/5 |
| `assist2PlayerTotal` | 3/5 |

The four `assist*` fields are nullable as expected: a goal can have 0,
1, or 2 assists. Sample had at least one unassisted goal and at least
one with a single assist.

#### `missed-shot` (n=22)

| key | present |
|-----|--------:|
| `eventOwnerTeamId` | 22/22 |
| `goalieInNetId` | 22/22 |
| `reason` | 22/22 |
| `shootingPlayerId` | 22/22 |
| `shotType` | 22/22 |
| `xCoord` | 22/22 |
| `yCoord` | 22/22 |
| `zoneCode` | 22/22 |

#### `blocked-shot` (n=34)

| key | present |
|-----|--------:|
| `blockingPlayerId` | 34/34 |
| `eventOwnerTeamId` | 34/34 |
| `reason` | 34/34 |
| `shootingPlayerId` | 34/34 |
| `xCoord` | 34/34 |
| `yCoord` | 34/34 |
| `zoneCode` | 34/34 |

Note: `eventOwnerTeamId` on blocked shots is the **blocking** team
(the team that recorded the block as their event), not the shooter's
team. Worth a parser comment because the naming is easy to misread.

#### `faceoff` (n=48)

| key | present |
|-----|--------:|
| `eventOwnerTeamId` | 48/48 |
| `losingPlayerId` | 48/48 |
| `winningPlayerId` | 48/48 |
| `xCoord` | 48/48 |
| `yCoord` | 48/48 |
| `zoneCode` | 48/48 |

Confirms spike-§5: faceoffs use `winningPlayerId`/`losingPlayerId`,
not the earlier-API `homePlayerId`/`awayPlayerId` shape.

#### `hit` (n=67)

| key | present |
|-----|--------:|
| `eventOwnerTeamId` | 67/67 |
| `hitteePlayerId` | 67/67 |
| `hittingPlayerId` | 67/67 |
| `xCoord` | 67/67 |
| `yCoord` | 67/67 |
| `zoneCode` | 67/67 |

#### `giveaway` (n=26)

| key | present |
|-----|--------:|
| `eventOwnerTeamId` | 26/26 |
| `playerId` | 26/26 |
| `xCoord` | 26/26 |
| `yCoord` | 26/26 |
| `zoneCode` | 26/26 |

#### `takeaway` (n=11)

| key | present |
|-----|--------:|
| `eventOwnerTeamId` | 11/11 |
| `playerId` | 11/11 |
| `xCoord` | 11/11 |
| `yCoord` | 11/11 |
| `zoneCode` | 11/11 |

#### `penalty` (n=15)

| key | present |
|-----|--------:|
| `committedByPlayerId` | 15/15 |
| `descKey` | 15/15 |
| `drawnByPlayerId` | 15/15 |
| `duration` | 15/15 |
| `eventOwnerTeamId` | 15/15 |
| `typeCode` | 15/15 |
| `xCoord` | 15/15 |
| `yCoord` | 15/15 |
| `zoneCode` | 15/15 |
| `servedByPlayerId` | 2/15 |

`servedByPlayerId` is sparse — appears on bench-minor or
goaltender penalties where a designated teammate serves the time.

#### `delayed-penalty` (n=6)

| key | present |
|-----|--------:|
| `eventOwnerTeamId` | 6/6 |

Notably no coordinates and no player IDs. The delayed-penalty event
marks the *signal*, not the infraction itself; the matching `penalty`
event carries the offender. Parser implication: don't expect
`xCoord`/`yCoord` here even though every other event with `details`
has them.

#### `stoppage` (n=35)

| key | present |
|-----|--------:|
| `reason` | 35/35 |
| `secondaryReason` | 10/35 |

No team or player IDs and no coordinates on stoppages. `reason` is a
free-form string (e.g. `"icing"`, `"goalie-stopped-after-sog"`).

### `rosterSpots[*]` keys

Every `rosterSpot` entry carries: `firstName` (i18n dict),
`headshot` (URL), `lastName` (i18n dict), `playerId`, `positionCode`,
`sweaterNumber`, `teamId`. 40/40 in the sample. Spike-§3 already
flagged this lives on play-by-play, not boxscore.

## Parser-design takeaways

These shape PR-D's `PlayByPlayResponse` and downstream silver
modeling work:

1. **Schema posture.** Pin `id`, `season`, `gameDate`, `plays` (list),
   `rosterSpots` (list) on `PlayByPlayResponse`. Don't pin per-event
   `details` shapes — every other field rides along in
   `response_json` and silver (M3) reconciles. The bronze contract is
   "preserve the verbatim payload"; we'd rather absorb future event
   types silently than have ingest fail mid-backfill on a new
   `typeDescKey`.

2. **Coord/zone universality.** `xCoord`, `yCoord`, `zoneCode` are
   present on every event with `details` *except* `delayed-penalty`,
   `stoppage`, and the three structural types that have no `details`
   at all. That's a small enough exception list to encode as a known
   set in the silver event-unnest dbt model.

3. **Player ID column inconsistency is intentional.** Different event
   types name the same role differently — `playerId` on
   give/takeaways, `shootingPlayerId` on shots, `committedByPlayerId`
   on penalties, `winningPlayerId`/`losingPlayerId` on faceoffs. Don't
   try to canonicalize at the bronze loader level; do it once in
   silver against an explicit per-event mapping.

4. **Marketing-asset fields on `goal`.** `discreteClip`,
   `highlightClip`, `highlightClipSharingUrl`, and the three `*Fr`
   French-locale variants are CMS URLs, not modeling features. Flag
   for exclusion when M3 unnests goal events; they balloon row
   width for no analytical value.

5. **Empty `details`.** Allowed only for `period-start`,
   `period-end`, `game-end`. Any other `typeDescKey` arriving with no
   `details` block is upstream drift and should fail loud at silver,
   not bronze (bronze must stay tolerant; silver is where shape
   contracts live).

These notes get absorbed into ADR-0003 by PR-H along with
[`pra-spike-notes.md`](./pra-spike-notes.md). Both files are deleted
once the ADR lands.
