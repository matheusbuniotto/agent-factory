---
id: factory.contracts
title: Data contracts
version: 1
depends_on: []
provides: [Task, Source, Spec, Kind, Size, Scenario, Example, Check, Review, Verdict]
generated_artifact: factory/contracts.py
status: accepted
---

# Data contracts

## Purpose

This doc defines the plain data that passes between factory steps and agents.
Contracts carry no I/O. Their only behaviour is `Spec.gaps()` plus markdown
rendering, so a person can read every artifact.

## Scope

In scope: task, spec (the design doc), check result, review.
Out of scope: run state and persistence (`factory.run`), configuration (`factory.config`).

## Semantic contract

| Model      | Produced by        | Consumed by                     |
|------------|--------------------|---------------------------------|
| `Task`     | `intake`           | planner, run                    |
| `Spec`     | planner agent      | gate, implementer, reviewer, scribe |
| `Check`    | `checks`           | pipeline (feedback), run artifacts |
| `Review`   | reviewer agent     | pipeline (rework), ship         |

### Spec minimum (step 3.1)

`Spec.gaps()` returns a list of human-readable gaps. An empty list means the
spec is buildable.

| Requirement                          | simple | standard |
|--------------------------------------|:------:|:--------:|
| non-empty `purpose`                  | yes    | yes      |
| ≥1 `scenarios`                       | yes    | yes      |
| ≥1 `acceptance`                      | yes    | yes      |
| ≥1 `out_of_scope`                    |        | yes      |
| ≥1 `must_not_infer`                  |        | yes      |
| ≥1 success `examples`                |        | yes      |
| ≥1 failure `examples`                |        | yes      |

## Public interface

```python
class Task(BaseModel):     title, body, source, url; to_markdown()
class Spec(BaseModel):     title, kind, size, purpose, in_scope, out_of_scope,
                           scenarios, examples, interface, invariants,
                           must_not_infer, acceptance, assumptions,
                           open_questions, sources; gaps(); to_markdown()
class Check(BaseModel):    command, passed, output
class Review(BaseModel):   verdict, summary, comments; approved; to_markdown()
```

## Worked example: simple spec with a gap

```yaml
input:  {title: "Add subtract", kind: software, size: simple,
         purpose: "Subtract two numbers", scenarios: [one], acceptance: []}
output: ["missing acceptance"]
```

## Worked example: standard spec without a failure example

```yaml
input:  {size: standard, examples: [{name: ok, failure: false}], ...all else filled}
output: ["missing failure example"]
```

## Must not infer

- Contracts perform no file, network, or subprocess I/O.
- `gaps()` never mutates the spec.
- Don't add fields a consumer doesn't read.

## Reconciliation anchor

```python
assert (
    Spec(
        title="t",
        kind="software",
        size="simple",
        purpose="p",
        scenarios=[Scenario(name="s", given="g", when="w", then="t")],
        acceptance=["pytest"],
    ).gaps()
    == []
)
assert Review(verdict="approve", summary="ok").approved
```

## Generated artifacts

- `factory/contracts.py`, `tests/test_contracts.py`
