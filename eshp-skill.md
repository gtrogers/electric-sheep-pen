# eshp — agent skill

## What it is

`memo` is a codebase-local knowledge graph. Notes live as plain-text `.eshp`
files in a `eshp/` folder; a SQLite graph index (`.eshp.db`) is kept in sync by
a background watcher or on-demand sync. Use it to record observations,
decisions, warnings, and typed relationships between concepts in the codebase.

## When to use it

| Situation | Action |
|-----------|--------|
| Starting a session on an unfamiliar codebase | `eshp search <topic>` to surface prior context |
| You learn something worth remembering | `eshp new <slug>` to create a note |
| Two concepts are related | `eshp relate` (write edge into the `.eshp` file) or edit directly |
| Exploring how things connect | `eshp graph <slug> --depth 2` |
| Recalling what exists in a domain | `eshp tag <tagname>` or `eshp tags` |

---

## Command reference

### Watch (recommended — run in background)
```
eshp watch [--root PATH]
```
Bootstraps the DB from all `.eshp` files then watches for changes. Keep this
running so every file edit is indexed immediately.

### Create a note
```
eshp new <slug> [--tags tag1,tag2] [--root PATH]
```
Creates `eshp/<slug>.eshp`, opens it in `$EDITOR`, and syncs on save.
- `slug` — kebab-case identifier, becomes the node ID in the graph
- `--tags` — comma-separated tags (no `#` prefix needed)

### Show a note
```
eshp show <slug> [--root PATH]
```
Prints the note body, tags, and all incoming/outgoing edges.

### Search
```
eshp search <query> [--tag TAG]... [--limit N] [--root PATH]
```
Full-text search over body text and slug names.
- Repeat `--tag` to require multiple tags simultaneously
- Default limit is 10

### Tags and relationships
```
eshp tags [--root PATH]              # all tags with note counts
eshp tag  <tagname> [--root PATH]    # notes carrying a specific tag
eshp rels [--root PATH]              # all relationship types with edge counts
eshp edges [--rel REL] [--root PATH] # all src --[rel]--> dst triples; optional rel filter
```
`#` prefix on `<tagname>` is optional.

### Graph neighbourhood
```
eshp graph <slug> [--depth N] [--rel REL] [--root PATH]
```
BFS from `<slug>` up to `--depth` hops (default 1).  
`--rel` filters to a single relationship type.

### Stats
```
eshp stats [--root PATH]
```
Prints note, tag, and edge counts.

---

## Note file format

```
#tag1 #tag2

Free text body. Observations, decisions, warnings — anything useful.

.relationship-name
-> target-slug
-> another-slug

.another-relationship
-> outgoing-slug
<- incoming-slug
```

- **First line(s)** starting with `#word` tokens → tags
- **Body** — free prose after a blank line
- **`.rel-name` sections** — typed edges
  - `->` this note points **to** target
  - `<-` target points **to** this note (reverse declaration)

---

## Typical agent workflow

### Session startup
```bash
eshp search <current task keywords>   # find relevant prior notes
eshp show <slug>                       # expand interesting hits
eshp graph <slug> --depth 2           # explore connections
eshp rels                              # understand how the graph is wired
eshp edges --rel <rel>                 # trace a specific relationship type
```

### Writing a new memory
```bash
eshp new auth-service --tags service,backend
# Edit the file that opens: add body text and relationships
```

### Connecting existing notes (edit directly)
Open `eshp/<slug>.eshp` and add a relationship section:
```
.depends-on
-> postgres
-> redis
```
The watcher picks up the change automatically; or run `eshp watch` first.

### Finding everything in a domain
```bash
eshp tag backend          # all notes tagged backend
eshp tags                 # overview of all tags
```

---

## Output format

All commands emit **plain text** suitable for piping into an LLM context window.
Colour formatting uses ANSI codes (suppressed when not connected to a terminal).
