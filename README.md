# Electric Sheep Pen

> **Alpha** — rough edges expected. Feedback welcome.

A codebase-local memory graph for AI coding agents. Plain-text `.eshp` files
live in an `eshp/` folder alongside your code. A SQLite graph store backs them
for fast querying. Everything commits to git.

Inspired by the A-mem paper (kind of).

---

## Why does this exist?

- Keep long term project memory out of proprietary coding agents and in git
- Provide persistent, structured memory across session boundaries or tool changes
- More easily read and reason about WTF the agent did
- Save on tokens and time by using the graph to warm-start context for coding sessions

---

## Install

Requires Python 3.11+.

```bash
pipx install git+https://github.com/gtrogers/electric-sheep-pen.git
```

Verify:

```bash
eshp --help
```

---

## Bootstrap an existing codebase

**1. Install the agent skills** into whichever AI tool you use:

```bash
cd myproject

eshp init-skills .github/skills    # GitHub Copilot
eshp init-skills .cursor/skills    # Cursor
eshp init-skills .rules/skills     # custom agents
```

This copies four skill templates into your agent's skills directory. Commit
them — they tell your agent how to use eshp.

**2. Start the watcher** to keep the graph DB live as you edit notes:

```bash
eshp watch
```

Or launch the visual web view (opens a graph in your browser):

```bash
eshp serve
```

**3. Add your first notes.** A good starting point for any codebase:

```bash
eshp new architecture       # high-level module layout
eshp new dev/conventions    # how to build, test, and commit
eshp new dev/workflow       # day-to-day dev commands
```

`eshp new` opens `$EDITOR`. Write what you'd want a new teammate — or your
future agent — to know. Add `#tags`, a `> description`, and `.relationships`
to other notes.

**4. Ask your agent a question.** With the `eshp--explain` skill installed,
your agent will query eshp before answering:

```
"Explain how the auth module works"
"Why does the edge direction work this way?"
"How do I add a new command?"
```

---

## The agent workflow

Four skills ship with eshp. They create a **read → act → write** loop:

| Skill | When to use |
|---|---|
| `eshp--explain` | Ask questions about the codebase |
| `eshp--plan` | Plan a feature — query eshp for context before implementing |
| `eshp--commit-and-dream` | After coding — commit, then update the memory graph |
| `eshp--deep-dream` | Periodic maintenance — resync graph accuracy with the codebase |

Each session the agent consults memory before starting, then enriches it after
finishing. The graph compounds: each session leaves it more useful than before.

---

## The `.eshp` file format

```
#tag1 #tag2

> One-line description shown when this note is referenced.

Free text body — prose, decisions, context, warnings.
Write what you'd want to know next time.

.relationship-name
-> target-slug
-> another-slug

.another-relationship
-> outgoing-slug
<- incoming-slug
```

- **Tags** — `#word` tokens on the first line(s)
- **Description** — `>` prefix, one line, shown in search results
- **Body** — free prose, separated from tags by a blank line
- **Relationships** — named sections starting with `.`
  - `->` outgoing edge: *this note* → *target*
  - `<-` incoming edge: *source* → *this note* (declared from this side)

Files live at `eshp/<slug>.eshp`. Slugs are root-relative paths without the
extension — `eshp/modules/auth.eshp` has slug `modules/auth`.

### Example

```
#service #backend #auth

> Handles user authentication and session management.

Uses JWT tokens with a 24h expiry. Token cache grows unbounded
under sustained load — caused two OOM incidents in production.

.depends-on
-> modules/postgres
-> modules/redis

.called-by
<- modules/api-gateway
```

---

## Commands

### Querying

| Command | Description |
|---|---|
| `eshp summarise` | Compact graph overview — total size, top tags, top rels, recent notes. Pipe into agent context at session start. |
| `eshp scan <query>` | Broad discovery — FTS + tag/rel name matching + 1-hop expansion, scored. Best starting point for agents. |
| `eshp recall <slug> [-n N]` | Full note + N direct neighbours with complete body. Default N=1. |
| `eshp show <slug>` | Single note body, tags, and edges. |
| `eshp search <query>` | Simple LIKE search across body and slug. |
| `eshp graph <slug>` | BFS tree. Use `--direction forward\|backward\|both`, `--rel`, `--depth`. |
| `eshp tag <tagname>` | All notes with a tag. |
| `eshp tags` | All tags with counts. |
| `eshp rels` | All relationship types with edge counts. |
| `eshp edges [--rel REL]` | All `src --[rel]--> dst` triples. |

### Editing

| Command | Description |
|---|---|
| `eshp new <slug>` | Create a skeleton note and open in `$EDITOR`. Syncs on exit. |
| `eshp watch` | Full sync on startup, then watches for file changes. |
| `eshp serve [--port 7842]` | Watcher + local Cytoscape.js graph view in browser. |

### Maintenance

| Command | Description |
|---|---|
| `eshp diagnose` | Graph health checks: orphans, dangling edges, stub notes, hubs. |
| `eshp stats` | Note, tag, and edge counts. |
| `eshp init-skills <path>` | Copy bundled agent skill templates to `<path>/`. |

---

## How it works

```
.eshp file  →  parse_eshp()  →  EshpNote  →  store.upsert_note()  →  SQLite
```

Four modules, each with one responsibility:

- `eshp_parser.py` — pure parse/render, no I/O side effects
- `eshp_store.py` — SQLite graph store (`notes`, `tags`, `edges` tables)
- `eshp_cli.py` — Click CLI + watchdog file watcher
- `eshp_server.py` — stdlib HTTP server for the web view (zero extra runtime deps)

The DB (`.eshp.db`) lives inside `eshp/` and is gitignored — regenerated from
the `.eshp` files by `eshp watch` or any sync call.

---

## Development

```bash
git clone https://github.com/gtrogers/electric-sheep-pen.git
cd electric-sheep-pen
pip install -e ".[dev]"
pytest
```
