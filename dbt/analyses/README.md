# Analyses

One-off exploratory SQL that benefits from dbt's ref/source resolution but
isn't a model we want to materialize. `dbt compile` renders these so you can
paste the compiled SQL into your warehouse client of choice.

Good fits:
- Ad-hoc CLV investigations
- Backtest-result slicing
- Data-quality spot checks that don't rise to the level of a persistent test

If an analysis gets rerun regularly, promote it to a mart.
