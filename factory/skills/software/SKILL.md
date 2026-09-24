---
name: software
description: Application and library code (Python, TypeScript, Go, Ruby...). Use for features, bug fixes and refactors in a regular codebase.
---

# Software

1. Find the existing pattern for what you are building and follow it: naming,
   layout, error handling, test style.
2. Write the test from the spec's acceptance and examples first, watch it fail,
   then make it pass.
3. Stay idiomatic. Pythonic in Python, Google style in Go, Rails conventions in Ruby.
4. Keep the change small. No drive-by refactors and no new dependencies unless the spec asks.
5. Run the project's own test and lint commands before you finish.
