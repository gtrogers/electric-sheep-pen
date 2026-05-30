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
  - `eshp tags` list all tags in the graph, tags are used to group topics
  - `eshp tag <tag>` list all notes with a given tag
  - `eshp show <tag>` show a note and it's connections to related notes
  - `eshp search` full text search - use only as a fallback if there are no relevant tags
- Also look at code, tests, etc
- Add new ideas, concepts and details to the memory graph (add entries to the ./eshp folder)
