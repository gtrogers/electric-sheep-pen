---
name: eshp--explain
description: Use the eshp memory graph to explain concepts and answer questions about the codebase
---

# ESHP Explain

ESHP (electric sheep pen) is a codebase-level memory graph that stores
structured knowledge about the project — architecture, design decisions,
conventions, commands, and domain concepts.

Use this skill to answer questions and explain concepts by querying the
memory graph for relevant context before responding.

Important: prefer `eshp scan <topic>` and `eshp recall <slug>` to reading
memory files directly.

## Inputs

A question or concept the user wants explained. This may be:
- A feature or command ("how does scan work?")
- An architecture or design question ("why does edge direction work this way?")
- A workflow question ("how do I add a skill?")
- A domain concept ("what is a slug?")

## Procedure

### 1. Warm start
Run `eshp summarise` to get an overview of the graph size, top tags, and
recently recalled notes. This tells you what's in the graph and what
topics have been active recently.

### 2. Broad discovery
Run `eshp scan <query>` with keywords from the user's question.

- Break compound questions into multiple scan terms
- Try synonyms if the first scan returns few results
  e.g. "explain the watcher" → `eshp scan watch` then `eshp scan file events`
- The scan output shows scored summaries (slug, desc, tags, edge_count)
  — use the scores and descriptions to pick the most relevant slugs

### 3. Focused context load
For the top 1–3 slugs from scan, run `eshp recall <slug>`.

- `recall` returns the full note body AND its closest neighbours
- Use `--n 2` or `--n 3` when you need broader context (e.g. the note links
  to several related concepts you also need)
- `recall` updates `last_recalled_at` automatically — this is useful metadata

### 4. Follow edges if needed
If the recalled notes reference slugs you haven't loaded yet and they seem
relevant, run `eshp recall <neighbour-slug>` on them.

Use `eshp graph <slug> --direction both --depth 2` to visualise the
neighbourhood when the concept spans many connected notes.

### 5. Answer
Synthesise an explanation from the retrieved context. Structure your answer
to match the question type:

- **"How does X work?"** → describe the mechanism, data flow, key methods
- **"Why does X work this way?"** → surface design decisions and rationale
  from note bodies (eshp notes often contain the "why")
- **"How do I do X?"** → give concrete steps or commands from the notes

Always cite which notes informed your answer (by slug). This helps the
user find more detail and helps future agents know what was consulted.

### 6. Flag gaps
If the graph doesn't have enough information to answer confidently, say so
clearly and suggest which slugs or tags are the closest available context.
Do not hallucinate — prefer a partial answer with honest uncertainty over
a confident but unsupported one.
