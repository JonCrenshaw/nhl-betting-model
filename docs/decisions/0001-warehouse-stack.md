# ADR-0001: Warehouse stack — R2 + DuckDB/MotherDuck + dbt

**Status.** Proposed
**Date.** 2026-04-22
**Deciders.** Jon

## Context

We need a data warehouse for V1 that is:
1. Cheap (< $20/month target).
2. Analytically fast over tabular/Parquet data.
3. Scriptable with dbt.
4. A stepping stone to something that can handle V2 subscriber load without a rewrite.

Jon is strong in SQL and wants to keep the transformation layer SQL-first. The warehouse must support this.

## Options considered

**Snowflake.**
- Pros: Industry standard, excellent tooling, scales to enterprise.
- Cons: Credit-based pricing punishes bursty workloads. Minimum warehouse idle costs add up. Overkill for V1 scale (millions, not billions, of rows).

**BigQuery.**
- Pros: Generous free tier (1 TB queried/month, 10 GB storage). Serverless, no idle cost. Strong ecosystem.
- Cons: GCP lock-in. Egress can surprise. Slightly more setup than DuckDB.
- Strong alternative, kept as a fallback.

**Postgres (Neon / Supabase / self-hosted).**
- Pros: Free tiers available. Familiar. Good for mixed OLTP/OLAP at small scale.
- Cons: Analytical query performance is meaningfully worse than columnar engines on Parquet. Will hurt at backtest time.

**DuckDB + MotherDuck (with Cloudflare R2 for object storage).**
- Pros: Columnar, extremely fast analytical queries. Reads Parquet directly over S3-compatible object storage. MotherDuck gives a hosted version with the same SQL. R2 has zero egress fees, which is critical because DuckDB hits object storage on every query. Trivial local development. Same dbt adapter across local and hosted.
- Cons: Newer than Snowflake/BQ; smaller ecosystem. MotherDuck is a young company (vendor risk). Concurrent-write story is weaker than Postgres if we ever needed that in the warehouse (we don't plan to).

## Decision

Adopt **Cloudflare R2 + DuckDB locally + MotherDuck for scheduled production + dbt for all transforms**.

Bronze (raw) data lives as date-partitioned Parquet in R2. Silver and gold live in DuckDB/MotherDuck and are materialized via dbt. Local developers read the same R2 bronze and run the same dbt project against local DuckDB.

## Consequences

**Positive.**
- V1 monthly warehouse cost estimate: ~$15 (MotherDuck $10 + R2 $2–5).
- Backtests will be fast because DuckDB reads Parquet over R2 with no egress fees.
- Local and production use identical SQL through dbt.
- Swapping MotherDuck for BigQuery or Snowflake in V2 is a dbt profile change plus minor macro fixes. Silver/gold SQL is largely portable.

**Negative.**
- MotherDuck is a startup; if it disappears we absorb migration work. Mitigation: keep bronze in R2, keep dbt project stateless, design every gold table as rebuildable.
- DuckDB's concurrent-write model means we must not use it as an OLTP database. Enforced by keeping transactional data in a separate Postgres (Neon) in Phase 2.
- Smaller talent pool familiar with this stack than with Snowflake. Offset by Claude in the loop and Jon's SQL fluency.

**Neutral.**
- Dagster assets will wrap both Python loaders and dbt models; one lineage graph across both.

## Revisit trigger

We revisit this decision if any of:
- Warehouse exceeds 100 GB of silver+gold data (MotherDuck pricing gets less attractive at scale).
- We start serving subscriber reads directly from the warehouse at a rate that creates concurrency issues (should instead add a caching layer or read replica, but this ADR should be reconsidered too).
- MotherDuck materially changes pricing or product direction.
- We need multi-writer transactional semantics in the warehouse (we shouldn't — transactional data belongs elsewhere).
