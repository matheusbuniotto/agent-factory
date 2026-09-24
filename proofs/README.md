# Proofs

`Factory.lean` models the factory's pure decision logic and proves what the rest
of the code relies on:

| Python                            | Proved                                                                    |
|-----------------------------------|---------------------------------------------------------------------------|
| `hooks.starts`                    | no run without the trigger label; created or newly labelled tickets start; updates to an already-labelled ticket, edits, and other labels never start a second run |
| `config.Dispatch.lane`            | the default unless a task label maps to a lane; the first one wins; a non-default lane always comes from one of the task's labels |
| `run.Run.status`, `rewind`        | done exactly when every step is; rewind keeps earlier steps, resets later ones, and resume picks up at the rewind point |

Lean checks the model, not the Python. Each model copies its Python function
line for line; change both together.

```bash
curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh   # once
cd proofs && lean Factory.lean   # silent means every proof checks
```
