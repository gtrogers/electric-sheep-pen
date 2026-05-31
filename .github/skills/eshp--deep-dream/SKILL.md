---
name: eshp--deep-dream
description: Do deep maintenance on the eshp memory graph files, ensure the mem-graph is in sync with the codebase
---

# ESHP Deep Dream

ESHP (electric sheep pen) is a codebase level memory graph for maintaining
information about the current project.

This skill is for doing deep maintenance on the graph, ensuring is it up
to date and that the relationships are mapped correctly.

## Procedure

Ensure the git state is clean so we can commit the updated memory files.

Run diagnostics first — use the output as your work queue:

```
eshp diagnose
```

- Fix **dangling edges** immediately (broken connections are data corruption)
- Resolve **orphaned nodes** — link them into the graph or delete if stale
- Note **bloated notes**, **hub nodes**, and **stubs** — address if time allows; otherwise document in the commit message

Understand the current memory graph

- `eshp rels` - list all relationships
- `eshp tags` - list all tags
- `eshp summarise` - list recently created and recalled memories

Understand the current codebase

- High level goals
- Features and capabilities
- Developer guidance and lifecycle
- Any upcoming or planned features
- Issues, refactoring opportunities, etc

Ensure the memory graph is an accurate reflaction of the project and
covers planned and existing features, dev lifecycle, and crucial knowledge.
Key questiona: if the code was removed could we recreated the project
from the memory graph alone?

Maintain memory accuracy

- use `eshp scan <query>` and `eshp recall <slug>` to check for accuracy
- use `eshp tags` and look for opportunities to consolidate similar tags
- use `eshp rels` and look for opportunities to consolidate similar relationships
- add any missing entries
- add any missing tags or relationships

Once done commit the updated memory graph files as a new deep-dream commit.
