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


# Scoring weights for scan()
_SCORE_SLUG_EXACT   = 100
_SCORE_TAG_EXACT    =  60
_SCORE_REL_EXACT    =  40
_SCORE_SLUG_PARTIAL =  20
_SCORE_TAG_PARTIAL  =  10
_SCORE_REL_PARTIAL  =   5
_SCORE_BODY_PARTIAL =   3
_SCORE_NEIGHBOR     =   1


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
        # Migrate existing DBs that predate the last_recalled_at column
        try:
            self.conn.execute("ALTER TABLE notes ADD COLUMN last_recalled_at TEXT DEFAULT NULL")
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
        # Clean orphan incoming edges (e.g. from a previously malformed <- line)
        c.execute(
            "DELETE FROM edges WHERE dst=? AND src NOT IN (SELECT slug FROM notes)",
            (note.slug,),
        )

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

    def all_rels(self) -> list[tuple[str, int]]:
        """Return all relationship types with their edge counts, sorted by count desc."""
        return [
            (r["rel"], r["cnt"]) for r in self.conn.execute(
                "SELECT rel, COUNT(*) as cnt FROM edges GROUP BY rel ORDER BY cnt DESC"
            )
        ]

    def all_edges(self, rel: Optional[str] = None) -> list[dict]:
        """Return all edges as {src, rel, dst}, optionally filtered by rel name."""
        if rel:
            rows = self.conn.execute(
                "SELECT src, rel, dst FROM edges WHERE rel=? ORDER BY rel, src, dst", (rel,)
            )
        else:
            rows = self.conn.execute(
                "SELECT src, rel, dst FROM edges ORDER BY rel, src, dst"
            )
        return [dict(r) for r in rows]

    def subgraph(
        self,
        slug: str,
        rels: Optional[list] = None,
        depth: int = 3,
        direction: str = "both",
    ) -> list[dict]:
        """BFS from slug, optionally filtered to specific relationship types.

        direction:
          'forward'  — follow edges where src is in frontier (src → dst)
          'backward' — follow edges where dst is in frontier (traversed in reverse)
          'both'     — follow edges in either direction (default)

        Returns list of {src, rel, dst, hop, traversal_dir} where:
          hop           — 1-based traversal depth
          traversal_dir — 'forward' or 'backward' (how the edge was traversed)

        Edges to already-visited nodes are included in the result but those
        nodes are not added to the next frontier.
        """
        visited = {slug}
        frontier = {slug}
        result = []

        for hop in range(1, depth + 1):
            if not frontier:
                break
            placeholders = ",".join("?" * len(frontier))
            if direction == "forward":
                sql = f"SELECT src, rel, dst FROM edges WHERE src IN ({placeholders})"
                params = list(frontier)
            elif direction == "backward":
                sql = f"SELECT src, rel, dst FROM edges WHERE dst IN ({placeholders})"
                params = list(frontier)
            else:  # both
                sql = (
                    f"SELECT src, rel, dst FROM edges "
                    f"WHERE src IN ({placeholders}) OR dst IN ({placeholders})"
                )
                params = list(frontier) * 2

            next_frontier = set()
            for row in self.conn.execute(sql, params):
                r = dict(row)
                if rels and r["rel"] not in rels:
                    continue
                if direction == "forward":
                    tdir, new_node = "forward", r["dst"]
                elif direction == "backward":
                    tdir, new_node = "backward", r["src"]
                else:
                    if r["src"] in frontier:
                        tdir, new_node = "forward", r["dst"]
                    else:
                        tdir, new_node = "backward", r["src"]
                result.append({**r, "hop": hop, "traversal_dir": tdir})
                if new_node not in visited:
                    visited.add(new_node)
                    next_frontier.add(new_node)
            frontier = next_frontier

        return result

    def stats(self) -> dict:
        return {
            "notes": self.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0],
            "tags":  self.conn.execute("SELECT COUNT(DISTINCT tag) FROM tags").fetchone()[0],
            "edges": self.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
        }

    def record_recall(self, slug: str) -> None:
        """Record that a note was recalled (updates last_recalled_at). Auto-commits."""
        self.conn.execute(
            "UPDATE notes SET last_recalled_at = datetime('now') WHERE slug = ?", (slug,)
        )
        self.conn.commit()

    def summarise(self, top_n: int = 10) -> dict:
        """Return a compact summary of the graph for agent context injection.

        Returns a dict with:
          stats          — note/tag/edge counts
          top_tags       — [(tag, count), ...] top N by count
          top_rels       — [(rel, count), ...] top N by count
          recent_notes   — [{slug, desc, updated_at}, ...] most recently updated
          recent_recalls — [{slug, desc, last_recalled_at}, ...] most recently recalled
        """
        return {
            "stats": self.stats(),
            "top_tags": self.all_tags()[:top_n],
            "top_rels": self.all_rels()[:top_n],
            "recent_notes": [
                dict(r) for r in self.conn.execute(
                    "SELECT slug, desc, updated_at FROM notes "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (top_n,),
                )
            ],
            "recent_recalls": [
                dict(r) for r in self.conn.execute(
                    "SELECT slug, desc, last_recalled_at FROM notes "
                    "WHERE last_recalled_at IS NOT NULL "
                    "ORDER BY last_recalled_at DESC LIMIT ?",
                    (top_n,),
                )
            ],
        }

    def scan(self, query: str, limit: int = 20) -> list[dict]:
        """Scored broad search: slug, tag, rel name, body, and 1-hop expansion.

        Each signal contributes points; scores accumulate across multiple matches.
        Results are returned sorted by score descending, trimmed to `limit`.
        Each result has: slug, desc, tags, body_preview, edge_count, score.
        """
        scores: dict[str, float] = {}
        q = query.lower()

        def bump(slug: str, points: float) -> None:
            scores[slug] = scores.get(slug, 0) + points

        # 1. Slug exact / partial
        for r in self.conn.execute(
            "SELECT slug FROM notes WHERE lower(slug)=?", (q,)
        ):
            bump(r["slug"], _SCORE_SLUG_EXACT)
        for r in self.conn.execute(
            "SELECT slug FROM notes WHERE lower(slug) LIKE ? AND lower(slug)!=?",
            (f"%{q}%", q),
        ):
            bump(r["slug"], _SCORE_SLUG_PARTIAL)

        # 2. Tag exact / partial
        for r in self.conn.execute(
            "SELECT slug FROM tags WHERE lower(tag)=?", (q,)
        ):
            bump(r["slug"], _SCORE_TAG_EXACT)
        for r in self.conn.execute(
            "SELECT slug FROM tags WHERE lower(tag) LIKE ? AND lower(tag)!=?",
            (f"%{q}%", q),
        ):
            bump(r["slug"], _SCORE_TAG_PARTIAL)

        # 3. Rel name exact / partial (both ends of matching edges score)
        for r in self.conn.execute(
            "SELECT DISTINCT src, dst FROM edges WHERE lower(rel)=?", (q,)
        ):
            bump(r["src"], _SCORE_REL_EXACT)
            bump(r["dst"], _SCORE_REL_EXACT)
        for r in self.conn.execute(
            "SELECT DISTINCT src, dst FROM edges WHERE lower(rel) LIKE ? AND lower(rel)!=?",
            (f"%{q}%", q),
        ):
            bump(r["src"], _SCORE_REL_PARTIAL)
            bump(r["dst"], _SCORE_REL_PARTIAL)

        # 4. Body substring match
        for r in self.conn.execute(
            "SELECT slug FROM notes WHERE lower(body) LIKE ?", (f"%{q}%",)
        ):
            bump(r["slug"], _SCORE_BODY_PARTIAL)

        # 5. 1-hop neighbor expansion for all direct matches so far
        if scores:
            seeds = list(scores.keys())
            ph = ",".join("?" * len(seeds))
            for row in self.conn.execute(
                f"SELECT src, dst FROM edges WHERE src IN ({ph}) OR dst IN ({ph})",
                seeds * 2,
            ):
                for node in (row["src"], row["dst"]):
                    if node not in scores:
                        bump(node, _SCORE_NEIGHBOR)

        if not scores:
            return []

        # 6. Sort by score, take top `limit`, fetch note data
        ranked = sorted(scores, key=lambda s: scores[s], reverse=True)[:limit]
        ph = ",".join("?" * len(ranked))
        rows = {
            r["slug"]: dict(r)
            for r in self.conn.execute(
                f"SELECT n.slug, n.desc, n.body, group_concat(t.tag, ' ') AS tags "
                f"FROM notes n LEFT JOIN tags t ON t.slug=n.slug "
                f"WHERE n.slug IN ({ph}) GROUP BY n.slug",
                ranked,
            )
        }

        results = []
        for slug in ranked:
            if slug not in rows:
                continue  # referenced in an edge but never upserted as a note
            data = rows[slug]
            edge_count = self.conn.execute(
                "SELECT COUNT(*) FROM edges WHERE src=? OR dst=?", (slug, slug)
            ).fetchone()[0]
            body = data.get("body") or ""
            results.append({
                "slug": slug,
                "desc": data.get("desc") or "",
                "tags": data.get("tags") or "",
                "body_preview": body[:200].replace("\n", " "),
                "edge_count": edge_count,
                "score": scores[slug],
            })

        return results

    def recall(self, slug: str, n: int = 5) -> Optional[dict]:
        """Return a full note and its N closest related notes (direct 1-hop neighbors).

        Returns None if the slug is not found.
        Each related note includes full body, desc, tags, and edges.
        """
        note = self.get_note(slug)
        if note is None:
            return None

        edges = self.neighbours(slug, depth=1)
        neighbor_slugs: list[str] = []
        seen: set[str] = {slug}
        for e in edges:
            for node in (e["src"], e["dst"]):
                if node not in seen:
                    seen.add(node)
                    neighbor_slugs.append(node)

        related = []
        for ns in neighbor_slugs[:n]:
            neighbor_note = self.get_note(ns)
            if neighbor_note is not None:
                related.append(neighbor_note)

        return {"note": note, "related": related}

    def close(self):
        self.conn.close()
