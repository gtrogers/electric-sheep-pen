---
name: eshp--plan
description: Plan and design features using the eshp memory graph
---

# ESHP-Plan
ElectricSheepPen (eshp) is a codebase level memory graph. It is
used to store and structure information about the code, project and
software lifecycle.

When given a spec file or a prompt describing a feature or change
to the codebase use eshp to understand the current codebase and
dev flow, plan out changes and keep track of progress.

## Inputs

A spec file or prompt from the user describing a feature or change
they want to make.

## Procedure

- Read the plan
- Query eshp to get relevant context:
  - `eshp scan <query>` broad discovery — FTS + tag names + 1-hop relation expansion; best starting point
  - `eshp recall <slug>` focused context load — full note + N closest related notes with body content
  - `eshp tags` list all tags in the graph, tags are used to group topics
  - `eshp tag <tag>` list all notes with a given tag
  - `eshp show <slug>` show a note and its connections to related notes
  - `eshp rels` list all relationship types ordered by frequency — useful for understanding how the graph is wired
  - `eshp edges [--rel REL]` list all src --[rel]--> dst triples; filter by rel name to explore a specific relationship type
- Also look at code, tests, etc
- Add new ideas, concepts and details to the memory graph (add entries to the ./eshp folder)
