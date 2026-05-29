"""
SQLite-backed graph store for eshp notes.

Schema:
  notes(slug, body, updated_at)
  tags(slug, tag)
  edges(src, rel, dst)          -- directed: src -[rel]-> dst
"""

import sqlite3
from pathlib import Path
from typing import Optional
from eshp_parser import EshpNote, parse_eshp


DB_FILE = ".eshp.db"


class EshpStore:
    def __init__(self, root: Path):
        self.root = root
        self.db_path = root / DB_FILE
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS notes (
                slug TEXT PRIMARY KEY,
                desc TEXT DEFAULT '',
                body TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS tags (
                slug TEXT,
                tag  TEXT,
                PRIMARY KEY (slug, tag)
            );
            CREATE TABLE IF NOT EXISTS edges (
                src  TEXT,
                rel  TEXT,
                dst  TEXT,
                PRIMARY KEY (src, rel, dst)
            );
            CREATE INDEX IF NOT EXISTS idx_tags_tag  ON tags(tag);
            CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
            CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
        """)
        # Migrate existing DBs that predate the desc column
        try:
            self.conn.execute("ALTER TABLE notes ADD COLUMN desc TEXT DEFAULT ''")
        except Exception:
            pass
        self.conn.commit()

    # ------------------------------------------------------------------ sync

    def sync(self, verbose: bool = False):
        """Scan the memo folder and sync all .memo files into the DB."""
        memo_files = list(self.root.glob("*.eshp"))
        seen_slugs = set()

        for path in memo_files:
            note = parse_eshp(path)
            self.upsert_note(note)
            seen_slugs.add(note.slug)
            if verbose:
                print(f"  synced: {note.slug}")

        # Remove notes whose files have been deleted
        existing = {r["slug"] for r in self.conn.execute("SELECT slug FROM notes")}
        for stale in existing - seen_slugs:
            self.delete_note(stale)
            if verbose:
                print(f"  removed: {stale}")

        self.conn.commit()
        return len(memo_files)

    def upsert_note(self, note: EshpNote):
        c = self.conn
        c.execute(
            "INSERT INTO notes(slug, desc, body, updated_at) VALUES(?,?,?,datetime('now')) "
            "ON CONFLICT(slug) DO UPDATE SET desc=excluded.desc, body=excluded.body, updated_at=excluded.updated_at",
            (note.slug, note.desc, note.body),
        )
        c.execute("DELETE FROM tags  WHERE slug=?", (note.slug,))
        c.execute("DELETE FROM edges WHERE src=?",  (note.slug,))

        for tag in note.tags:
            c.execute("INSERT OR IGNORE INTO tags(slug,tag) VALUES(?,?)", (note.slug, tag))

        for rel_name, target in note.all_outgoing:
            c.execute(
                "INSERT OR IGNORE INTO edges(src,rel,dst) VALUES(?,?,?)",
                (note.slug, rel_name, target),
            )
        # <- edges in a file mean: target -> this note
        for rel_name, source in note.all_incoming:
            c.execute(
                "INSERT OR IGNORE INTO edges(src,rel,dst) VALUES(?,?,?)",
                (source, rel_name, note.slug),
            )

    def delete_note(self, slug: str):
        self.conn.execute("DELETE FROM notes WHERE slug=?", (slug,))
        self.conn.execute("DELETE FROM tags  WHERE slug=?", (slug,))
        self.conn.execute("DELETE FROM edges WHERE src=? OR dst=?", (slug, slug))

    # ------------------------------------------------------------------ query

    def search(self, query: str, tags: Optional[list[str]] = None, limit: int = 10) -> list[dict]:
        """Full-text search over body + slug, optionally filtered by tags."""
        base_sql = """
            SELECT DISTINCT n.slug, n.desc, n.body,
                   group_concat(t.tag, ' ') AS tags
            FROM notes n
            LEFT JOIN tags t ON t.slug = n.slug
            WHERE (n.body LIKE ? OR n.slug LIKE ?)
        """
        params: list = [f"%{query}%", f"%{query}%"]

        if tags:
            placeholders = ",".join("?" * len(tags))
            base_sql += f" AND n.slug IN (SELECT slug FROM tags WHERE tag IN ({placeholders}) GROUP BY slug HAVING COUNT(DISTINCT tag)=?)"
            params.extend(tags)
            params.append(len(tags))

        base_sql += " GROUP BY n.slug LIMIT ?"
        params.append(limit)

        return [dict(r) for r in self.conn.execute(base_sql, params)]

    def get_note(self, slug: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT n.slug, n.desc, n.body, group_concat(t.tag,' ') AS tags "
            "FROM notes n LEFT JOIN tags t ON t.slug=n.slug "
            "WHERE n.slug=? GROUP BY n.slug",
            (slug,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["edges_out"] = [
            dict(r) for r in self.conn.execute(
                "SELECT rel, dst FROM edges WHERE src=?", (slug,)
            )
        ]
        result["edges_in"] = [
            dict(r) for r in self.conn.execute(
                "SELECT rel, src FROM edges WHERE dst=?", (slug,)
            )
        ]
        return result

    def neighbours(self, slug: str, rel: Optional[str] = None, depth: int = 1) -> list[dict]:
        """BFS neighbours up to `depth` hops."""
        visited = {slug}
        frontier = {slug}
        edges_found = []

        for _ in range(depth):
            if not frontier:
                break
            next_frontier = set()
            sql = "SELECT src, rel, dst FROM edges WHERE src IN ({}) OR dst IN ({})".format(
                ",".join("?" * len(frontier)),
                ",".join("?" * len(frontier)),
            )
            params = list(frontier) * 2
            for row in self.conn.execute(sql, params):
                r = dict(row)
                if rel and r["rel"] != rel:
                    continue
                edges_found.append(r)
                for node in (r["src"], r["dst"]):
                    if node not in visited:
                        visited.add(node)
                        next_frontier.add(node)
            frontier = next_frontier

        return edges_found

    def get_descs(self, slugs: list[str]) -> dict[str, str]:
        """Return {slug: desc} for the given slugs (missing slugs are omitted)."""
        if not slugs:
            return {}
        placeholders = ",".join("?" * len(slugs))
        rows = self.conn.execute(
            f"SELECT slug, desc FROM notes WHERE slug IN ({placeholders})", slugs
        )
        return {r["slug"]: r["desc"] for r in rows}

    def list_by_tag(self, tag: str) -> list[str]:
        return [
            r["slug"] for r in self.conn.execute(
                "SELECT slug FROM tags WHERE tag=? ORDER BY slug", (tag,)
            )
        ]

    def all_tags(self) -> list[tuple[str, int]]:
        return [
            (r["tag"], r["cnt"]) for r in self.conn.execute(
                "SELECT tag, COUNT(*) as cnt FROM tags GROUP BY tag ORDER BY cnt DESC"
            )
        ]

    def stats(self) -> dict:
        return {
            "notes": self.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0],
            "tags":  self.conn.execute("SELECT COUNT(DISTINCT tag) FROM tags").fetchone()[0],
            "edges": self.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
        }

    def close(self):
        self.conn.close()
