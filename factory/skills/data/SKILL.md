---
name: data
description: dbt models, SQL and data pipelines. Use when the task touches models, sources, tests or transformations of tabular data.
---

# Data

1. In dbt projects, follow the existing layers (staging → intermediate → marts)
   and naming (`stg_`, `int_`, `fct_`, `dim_`).
2. Every new model gets a `schema.yml` entry with a description, and `unique`
   plus `not_null` tests on its grain.
3. Build and test only what changed: `dbt build --select state:modified+` or
   `dbt build --select <model>+`.
4. Never run against production targets. Use the dev target from `profiles.yml`.
5. Make transformations idempotent. Re-running must give the same rows.
