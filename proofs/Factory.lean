/-!
# Proofs for the factory's decision logic

Each section models one pure Python function, line for line, and proves the
properties the rest of the factory relies on. Lean checks the model, not the
Python: keep the two in sync (the Python docstrings point here).

Check with `lean Factory.lean` in this directory.
-/

namespace Factory

/-! ## Webhooks: `factory.hooks.starts`

```python
def starts(trigger, labels, created, before):
    return trigger in labels and (created or (before is not None and trigger not in before))
```
-/

def starts (trigger : String) (labels : List String) (created : Bool) (before : Option (List String)) : Bool :=
  labels.contains trigger && (created || match before with
    | some b => !b.contains trigger
    | none => false)

/-- Safety: no ticket starts a run without the trigger label. -/
theorem starts_needs_trigger {t ls c b} (h : starts t ls c b = true) : t ∈ ls := by
  simp [starts] at h
  exact h.1

/-- A ticket created with the trigger label starts a run. -/
theorem created_with_trigger_starts {t ls b} (h : t ∈ ls) : starts t ls true b = true := by
  simp [starts, h]

/-- Adding the trigger label to an existing ticket starts a run. -/
theorem adding_trigger_starts {t ls b} (now : t ∈ ls) (was : t ∉ b) : starts t ls false (some b) = true := by
  simp [starts, now, was]

/-- No second run: an update to a ticket that already had the trigger label never starts one. -/
theorem no_restart {t ls b} (h : t ∈ b) : starts t ls false (some b) = false := by
  simp [starts, h]

/-- Edits that don't touch labels (no `before`) never start a run. -/
theorem edits_never_start {t ls} : starts t ls false none = false := by
  simp [starts]

/-- GitHub's `labeled` event names the one label added, so `before` is the labels without it.
Adding any other label never starts a run. -/
theorem github_other_label_never_starts {t added ls} (h : added ≠ t) :
    starts t ls false (some (ls.filter (· != added))) = false := by
  by_cases mem : t ∈ ls
  · have : t ∈ ls.filter (· != added) := List.mem_filter.mpr ⟨mem, by simp [Ne.symm h]⟩
    exact no_restart this
  · simp [starts, mem]

/-! ## Lanes: `factory.config.Dispatch.lane`

```python
def lane(self, labels):
    return next((self.labels[label] for label in labels if label in self.labels), self.default)
```
-/

inductive Lane | «local» | sqs
  deriving DecidableEq

def lane (rules : List (String × Lane)) (default : Lane) (labels : List String) : Lane :=
  (labels.findSome? (List.lookup · rules)).getD default

/-- Labels order the rules: the first configured label wins, whatever follows it. -/
theorem lane_first {rules d l rest x} (h : List.lookup l rules = some x) : lane rules d (l :: rest) = x := by
  simp [lane, List.findSome?, h]

/-- Unconfigured labels are skipped. -/
theorem lane_skip {rules d l rest} (h : List.lookup l rules = none) : lane rules d (l :: rest) = lane rules d rest := by
  simp [lane, List.findSome?, h]

/-- With no configured label on the task, the default lane is used. -/
theorem lane_default {rules d labels} (h : ∀ l ∈ labels, List.lookup l rules = none) : lane rules d labels = d := by
  induction labels with
  | nil => rfl
  | cons l rest ih =>
    rw [lane_skip (h l (by simp))]
    exact ih (fun l' m => h l' (by simp [m]))

/-- A non-default lane always comes from a rule matching one of the task's labels. -/
theorem lane_from_a_label {rules d labels} (h : lane rules d labels ≠ d) :
    ∃ l ∈ labels, List.lookup l rules = some (lane rules d labels) := by
  induction labels with
  | nil => exact absurd rfl h
  | cons l rest ih =>
    cases e : List.lookup l rules with
    | some x => exact ⟨l, by simp, by rw [lane_first e, e]⟩
    | none =>
      rw [lane_skip e] at h ⊢
      obtain ⟨l', m, r⟩ := ih h
      exact ⟨l', by simp [m], r⟩

/-! ## Runs: `factory.run.Run.status`, `next_step` and `rewind`

```python
status    = next((s.status for s in steps if s.status is not DONE), DONE)
next_step = next((s.name for s in steps if s.status is not DONE), None)   # modelled as an index
rewind(i) : steps[i:] = [pending] * len(steps[i:])
```
-/

inductive Status | pending | running | done | failed | escalated
  deriving DecidableEq

def status (steps : List Status) : Status :=
  (steps.find? (· ≠ .done)).getD .done

def nextStep (steps : List Status) : Nat :=
  steps.findIdx (· ≠ .done)

def rewind (i : Nat) (steps : List Status) : List Status :=
  steps.take i ++ List.replicate (steps.length - i) .pending

/-- A run is done exactly when every step is. -/
theorem status_done_iff {steps} : status steps = .done ↔ ∀ s ∈ steps, s = .done := by
  induction steps with
  | nil => simp [status]
  | cons s rest ih =>
    by_cases h : s = .done
    · simp [status, List.find?, h] at ih ⊢
      exact ih
    · simp [status, List.find?, h]

/-- Rewinding keeps the number of steps. -/
theorem rewind_length {i steps} (h : i ≤ steps.length) : (rewind i steps).length = steps.length := by
  simp [rewind]
  omega

/-- Rewinding never touches the steps before the rewind point. -/
theorem rewind_keeps_earlier {i steps} : (rewind i steps).take i = steps.take i := by
  by_cases h : i ≤ steps.length
  · simp [rewind, Nat.min_eq_left h]
  · simp [rewind, show steps.length - i = 0 by omega, List.take_take]

/-- Every step from the rewind point on is pending again. -/
theorem rewind_resets_later {i steps} : ∀ s ∈ (rewind i steps).drop i, s = .pending := by
  intro s m
  simp only [rewind, List.drop_append, List.drop_take_self, List.nil_append] at m
  exact (List.mem_replicate.mp (List.mem_of_mem_drop m)).2

/-- Resume after a rewind picks up exactly at the rewind point, when the steps before it are done. -/
theorem rewind_resumes_at {i steps} (done : ∀ s ∈ steps.take i, s = .done) (h : i < steps.length) :
    status (rewind i steps) = .pending := by
  obtain ⟨k, later⟩ : ∃ k, steps.length - i = k + 1 := ⟨steps.length - i - 1, by omega⟩
  simp only [status, rewind, List.find?_append, later, List.replicate_succ]
  rw [List.find?_eq_none.mpr (by simpa using done)]
  rfl

end Factory
