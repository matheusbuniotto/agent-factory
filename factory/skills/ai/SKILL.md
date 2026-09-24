---
name: ai
description: ML and LLM engineering - training code, evals, prompts, agents, model serving. Use when the task changes model behaviour or AI pipelines.
---

# AI engineering

1. Every behaviour change comes with an eval: a small fixed dataset and a score
   checked in, runnable offline.
2. Tests must not call paid APIs. Use test or mock models (for example
   `pydantic_ai.models.test.TestModel`), and fix seeds.
3. Keep prompts in one place, versioned with the code, never built from scattered strings.
4. Record model names and parameters in config, not in code.
5. Report cost and latency impact in your summary when you change a model call.
