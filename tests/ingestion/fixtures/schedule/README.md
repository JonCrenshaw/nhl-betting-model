# Schedule NHL API fixtures

Hand-crafted schedule payloads used by `tests/ingestion/test_schedule.py`
to exercise the daily walker without hitting the network. Synthesized
rather than recorded — we control the mix of game states and dates so
each branch of the filter logic is exercised.

| File | Anchor date | Contents |
|------|-------------|----------|
| `schedule_2026-04-24.json` | 2026-04-24 | 3-day `gameWeek` slice. The 04-24 day has three games: `2025030123` (`OFF`, ingestible — matches the game-level fixtures in `../games/`), `2025030124` (`LIVE`, must skip), `2025030125` (`FUT`, must skip). The 04-23 day has one ingestible game (`2025030120`) which the date filter must exclude when the target is 04-24. |

All synthetic game IDs satisfy the spike-§7 invariant
(`id // 1_000_000 == int(str(season)[:4])`) so the
`GameResponseBase._validate_game_id_format` model validator passes on
every game in the response.

Refresh policy: only update if a parser change requires shape we don't
currently exercise. When updating, keep `2025030123` as the
ingestible game so the existing landing/boxscore/play-by-play fixtures
remain compatible.
