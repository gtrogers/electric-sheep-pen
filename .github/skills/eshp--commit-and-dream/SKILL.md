---
name: eshp--commit-and-dream
description: Commit the current WIP to git and then update the memory graph via a dream step
---

# ESHP Commit and Dream

ESHP (electric sheep pen) is a codebase level memory graph designed
to be stored in git. Use it to maintain knowledge about the current
project.

Important: prefer `eshp recall <slug>` and `eshp scan <topic>` to
reading memory files directly.

## Commit

- Check everything works: run all tests, ensure git is in a clean state
- Commit to git following any established rules or conventions

## Dream

After committing...

- Reflect on the coding session and ensure the eshp memory graph is
  up to date.
- Do not try to maintain the entire graph, focus on updating, adding
  or pruning information based on the recent session.
- Things to check
  - Facts: are relevant files up to date and correct
  - Relationships: are files linked together correctly, do relationships need to be added or removed?

### What to add and update

Relevant information:
 - What would be useful to know next time?
 - What would be useful to a new engineer joining with zero context?
 - What knowledge would significantly speed up future work?
 - What knowledge would help people avoid common pitfalls and mistakes (relevant to this codebase)

Salient information:
 - What's interesting or different?
 - What's dangerous (traps, sharp edges, pitfalls)?

Types of information:
 - About key classes, features and functionality
 - Domain concepts and rules
 - Bugs, issues, features (both completed and planned)
 - Key changes or refactorings

Types of relationship:

## What to prune

- Information that is no longer relevant (e.g. superseded by something else)
- Information that only existed as a temporary memo or "todo"
- Relationships that no longer make sense
