
## Main Steps
0. intake (text, local.md, github issue)
1. Task understanding and classification
1.1 Prep enviroment = hydration if need and pre-commit setup, sandboxing, worktres, resolve conflicts
2.1 [if need] Grilling alignment (opnional for non-autonomus one)
2.1 Discovery External research docs, examples, best pratices, recent docs/and stacks. Limit to at most 8 searchs
3. [if task is so simple = can be just a short doc combining both] Agent PM  BDD document + Design-domain docs (similar with @design-framework.md) from https://arxiv.org/html/2609.05364v1
3.1 Check determinist if we hvae at least the minimoum
4. Implementation agent w/ skills avaliable consuming the docs 
5. Linter/Checks/Precommits -> retry 2x if fail return to implementation with feedback, as if where github review. IF NOT pass, scalate to human instead of retry 3x
6. Agent Reviewer comparing code best pratices + implementation against goal and intent - can make small adjusments or come back to implementation (most 1x)
7. CI/finish work - commit 
8. PR (optinoal ) or send folder if not a remote.
9. Learning / what was done doc ELI5 -- goal is to onboard and keep user up to date;


## AGents
- Review agent should be different than implementation preferable
- Implementation agent must have access to skills to be easy to customize for distinct tasks (code/software, dbt/data or mlops/ai engineering)
- Hydratation can pull and start a micro-vm for code safety execution
- Autonomous is the default behaviour.
- Research agent should be small
- Sub agents when make sense to save context for implmentation / review. Steps 1 to 3 can be 1 agent, implementation 1 agent, review othjer agent.
- Context is N1 priority, keep context thigh and autocompact at 170k of tokens usage.
- use minimal claude or pi or pydantic ai (~/pclaude example) /https://pydantic.dev/docs/ai/harness/  https://pydantic.dev/docs/ai/core-concepts/agent/  https://pydantic.dev/docs/ai/core-concepts/agent-spec/ https://pydantic.dev/docs/ai/examples/data-analytics/data-analyst/ 

## HITL (human in the loop)
- Ping user for critical decision, but system should aim to be autonomous
- Human review the bdd/design doc | human can answer grilling session | human can review the code at the end -- all done by flag and configs


## Transparency
- Keep steps easy to view, debug and rewind
- UI is important to check


## Reviwer App Github
- IF the remote is configured we can try to run the code review agent as an review app on gh,if not avaliable, just run normaly in a file with the handoff

## State 
- Keep sates, tools, check points to resume and restore for some checkpoints

## Docker
- Use docker like if we are using aws ECS or EC2 to deploy on native aws enviroment.
- Keep it simple to migrate to aws later

## Evals
- define a set of 2-3 use cases simple that are easy to evaluate in a json evals that run on CI.
- Be cost effective


## End goal 
Goal: is an agentic factory that can be autonomous or semi-autonmous runned safely on cloud customized by teams to adjust to their tasks and context with skills / capabilities .


