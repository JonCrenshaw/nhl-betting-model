# Tests (singular)

One-off SQL assertion tests that aren't general enough to be generic tests.
A test here is a SQL query that returns rows when the assertion **fails**;
dbt fails the test if any rows come back.

Example use cases:
- Cross-table invariants (every pick row has a matching `fct_games` row)
- Business-rule assertions (no pick can have EV > 50% without a manual review flag)

Generic, parametrized tests belong in `macros/tests/`. The built-in generic
tests (`unique`, `not_null`, `accepted_values`, `relationships`) come from
dbt itself and are declared in model `schema.yml` files.
