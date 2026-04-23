# Architecture Decision Records (ADRs)

Short, append-only records of significant technical decisions.

## When to write one

Write an ADR when:
- Choosing a vendor, service, or framework
- Making a schema change that affects silver or gold
- Changing orchestration, deployment, or security posture
- Adopting or retiring a modeling approach
- Any decision a new contributor (human or Claude) would otherwise have to reverse-engineer later

Do **not** write one for:
- Day-to-day code
- Bug fixes
- Dependencies bumps

## Format

One file per decision. Filename: `NNNN-short-kebab-title.md` where `NNNN` is the next sequential number.

Each ADR has these sections:

```markdown
# ADR-NNNN: Short title

**Status.** Proposed | Accepted | Superseded by ADR-XXXX
**Date.** YYYY-MM-DD
**Deciders.** Jon (+ anyone else)

## Context
What situation forced the decision? What are the constraints?

## Options considered
Brief bullets or short paragraphs per option.

## Decision
What we chose. One paragraph.

## Consequences
Positive, negative, and neutral consequences. Be honest about the downsides.

## Revisit trigger
What would cause us to reopen this decision?
```

## Rules

- **Never delete an ADR.** If we change our minds, write a new one that marks the old as "Superseded by".
- **Keep it short.** One page is a target, not a floor. If you need more, it probably belongs in an architecture doc with a link from the ADR.
- **Date it.** We revisit decisions over time; the date is load-bearing.
- **Be honest about tradeoffs.** ADRs that only list upsides are worthless.

## Current ADRs

- [0001 — Warehouse stack (R2 + DuckDB/MotherDuck + dbt)](./0001-warehouse-stack.md)
