# eshp

A codebase-local agentic memory graph. Plain text `.eshp` files in a `eshp/`
folder, backed by a SQLite graph store for fast querying.

Inspired by the [A-MEM paper](https://arxiv.org/abs/2502.12110) — memories as
interconnected notes with tags, free text, and typed relationships.

---

## File format

```
#tag1 #tag2

Free text body. Write anything here — context, observations,
warnings, decisions. This is the memory content.

.relationship-name
-> target-slug
-> another-slug

.another-relationship
-> outgoing-slug
<- incoming-slug
```

- **Tags** — `#word` tokens on the first line(s)
- **Body** — free prose, separated from tags by a blank line
- **Relationships** — named sections starting with `.`
  - `->` outgoing edge: *this note* points to *target*
  - `<-` incoming edge: *target* points to *this note* (reverse declaration)

Files live in `eshp/<slug>.eshp`. The slug is the filename without extension.

---

## Setup

```bash
pipx install .        # install as a standalone CLI tool
```

Or for development:

```bash
pip install -e ".[dev]"
pytest
```

---

## Commands

### `eshp new <slug>`
Create a new note and open it in `$EDITOR`. Auto-syncs on save.

```bash
eshp new auth-service --tags service,backend
```

### `eshp show <slug>`
Display a note's body, tags, and all graph edges (in and out).

```bash
eshp show auth-service
```

### `eshp search <query>`
Full-text search across all note bodies and slugs.

```bash
eshp search "memory pressure"
eshp search crash --tag backend
```

### `eshp tags`
List all tags with note counts.

```bash
eshp tags
```

### `eshp tag <tagname>`
List all notes carrying a tag.

```bash
eshp tag infra
eshp tag "#backend"   # # prefix optional
```

### `eshp graph <slug>`
Show the neighbourhood graph around a note.

```bash
eshp graph auth-service
eshp graph auth-service --depth 2
eshp graph auth-service --rel depends-on
```

### `eshp stats`
Show note, tag, and edge counts.

```bash
eshp stats
```

---

## Example `.eshp` file

```
#service #backend #auth

Handles user authentication and session management.
Uses JWT tokens with a 24h expiry. Has crashed twice
due to memory pressure when token cache grows unbounded.

.depends-on
-> postgres
-> redis

.related
-> api-gateway
```

---

## How it works

1. **Parse** — each `.eshp` file is parsed into tags, body text, and typed edges
2. **Store** — edges and tags are written to three SQLite tables: `notes`, `tags`, `edges`
3. **Query** — `search` does a `LIKE` scan; `graph` does BFS over the edge table
4. `<-` edges in a file are stored as forward edges in the DB (the other note
   pointing *to* this one), so relationships can be declared from either side

---

## Agent integration

The CLI is designed to be called from an LLM agent tool loop:

```
eshp watch                         # run in background to keep DB live
eshp search <query>                # retrieve relevant context
eshp show <slug>                   # expand a specific note
eshp graph <slug> --depth 2       # explore neighbourhood
eshp new <slug> --tags ...        # create new memory notes
```

All output is plain text, suitable for piping into an LLM context window.

See [`eshp-skill.md`](./eshp-skill.md) for a ready-to-use agent skill definition.
