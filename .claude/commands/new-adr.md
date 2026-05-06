---
description: Scaffold the next-numbered ADR in docs/decisions/.
---

## When to use

When the session has produced an architectural decision worth preserving — a vendor or framework choice, a schema change to silver/gold, an orchestration shift, or anything a future contributor (human or Claude) would otherwise have to reverse-engineer. The bar is in `docs/decisions/README.md`; if you're not sure, ask.

## Why it exists

ADRs are append-only and numbered sequentially. Getting the number, format, and front matter right by hand is friction that discourages writing them. This command removes that friction so the decision actually gets recorded.

## Behavior

1. Read `docs/decisions/README.md` to confirm the format and rules.
2. List existing ADRs in `docs/decisions/` to determine the next number.
3. Ask Jon for the inputs:
   - Title (one short phrase, kebab-case for the filename)
   - Status (Proposed | Accepted)
   - The context that forced the decision
   - Options considered (with honest pros/cons for each)
   - The decision and its consequences
   - A revisit trigger — what would make us reopen this?

4. Create the new file at `docs/decisions/<NNNN>-<slug>.md` following the template in `docs/decisions/README.md`. Use today's date in `YYYY-MM-DD` format. Do not modify other ADRs — they are append-only.

5. Update the "Current ADRs" list at the bottom of `docs/decisions/README.md` to include the new entry.

6. Reference the new ADR in any code, doc, or commit message the decision affects (e.g., `feat(warehouse): adopt DuckDB (ADR-0003)`).

## Notes

- An ADR with only upsides is worthless. Push back if Jon's inputs don't include real downsides.
- One page is a target, not a floor. If the decision needs more space, the supporting detail belongs in an architecture doc that the ADR links to — not in the ADR itself.
- If superseding a prior ADR, write the new one first, then edit the old one's status to `Superseded by ADR-NNNN`. Never delete an ADR.
