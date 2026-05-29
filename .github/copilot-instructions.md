# eshp — Copilot Instructions

## Commands

```bash
pip install -e ".[dev]"   # install with dev dependencies
pytest                     # run full test suite
pytest tests/test_parser.py::TestParseTags::test_single_tag  # run a single test
```

## Architecture

Three modules with a clean layered design:

- **`eshp_parser.py`** — Pure parse/render layer. Reads `.eshp` files into `EshpNote` dataclasses; `render_eshp` writes them back. No I/O side effects beyond reading the file.
- **`eshp_store.py`** — SQLite-backed graph store (`EshpStore`). Three tables: `notes`, `tags`, `edges(src, rel, dst)`. The `sync()` method does a full scan; `upsert_note()` / `delete_note()` handle incremental updates.
- **`eshp_cli.py`** — Click CLI. `find_eshp_root()` walks up from cwd to locate the `eshp/` directory. `EshpHandler` (watchdog) calls `upsert_note` / `delete_note` on file events.

**Key data flow:** `.eshp` file → `parse_eshp()` → `EshpNote` → `store.upsert_note()` → SQLite.

**Edge direction convention:** `<-` edges in a `.eshp` file are stored as *forward* edges in the DB (i.e., `source → this_note`). This means relationships can be declared from either side of a note, but the DB always stores them as `src -[rel]-> dst`.

**DB location:** `.eshp.db` lives inside the `eshp/` directory alongside the note files.

## Conventions

- **TDD**: write tests that capture assumptions first, then write code to make them pass.
- **Self-hosting**: use `eshp` itself during development to record decisions and context. The `eshp/` folder in this repo is the project's own memory graph.
- **Commit after mutations**: `EshpStore` does not auto-commit. Always call `store.conn.commit()` after `upsert_note()` / `delete_note()` in tests and production code.
- **Resource cleanup**: always call `store.close()` when done with an `EshpStore` instance.
- **Test structure**: tests are grouped into classes by method/feature (e.g. `TestParseTags`, `TestUpsertNote`). Use `tmp_path` for file isolation; the `store` and `memo_dir` fixtures in `test_store.py` are the canonical pattern for store tests.
- **Slugs**: kebab-case filenames without the `.eshp` extension. `path.stem` is used everywhere to derive them.
- **Tags**: stored without the `#` prefix in the DB and in `EshpNote.tags`; the `#` is only present in the raw file and stripped at parse time.
