#!/usr/bin/env python3
"""
eshp — agent-friendly CLI for a local Zettelkasten-style memory graph.

Usage:
  eshp watch                         Watch eshp/ and keep the DB live
  eshp new <slug> [--tags t1,t2]     Create a new note (opens $EDITOR)
  eshp show <slug>                   Show a note + its graph edges
  eshp search <query> [--tag t]      Full-text search
  eshp tags                          List all tags with counts
  eshp tag <tagname>                 List notes with a tag
  eshp graph <slug> [--depth 2]      Show neighbourhood graph
  eshp stats                         DB statistics
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import click
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent, FileDeletedEvent

from eshp_parser import EshpNote, parse_eshp, render_eshp
from eshp_store import EshpStore


def find_eshp_root() -> Path:
    """Walk up from cwd looking for an 'eshp' directory, or use ./eshp."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / "eshp"
        if candidate.is_dir():
            return candidate
    default = cwd / "eshp"
    default.mkdir(exist_ok=True)
    return default


def get_store(root: Optional[Path] = None) -> EshpStore:
    if root is None:
        root = find_eshp_root()
    return EshpStore(root)


# ──────────────────────────────────────────────────────────────────── helpers

def _note_header(slug: str, tags: str, desc: str = "") -> str:
    tag_str = f"  [{tags}]" if tags else ""
    header = f"{click.style(slug, fg='cyan', bold=True)}{click.style(tag_str, fg='yellow')}"
    if desc:
        header += f"\n  {click.style(desc, fg='white', dim=True)}"
    return header


def _edge_line(direction: str, rel: str, node: str, desc: str = "") -> str:
    arrow = click.style("->", fg="green") if direction == "out" else click.style("<-", fg="magenta")
    node_str = click.style(node, fg="cyan")
    if desc:
        node_str += f"  {click.style(desc, fg='white', dim=True)}"
    return f"  {arrow} {click.style(rel, fg='blue')} {node_str}"


def _open_in_editor(path: Path):
    editor = os.environ.get("EDITOR", "vi")
    subprocess.call([editor, str(path)])


# ──────────────────────────────────────────────────────────────── file watcher

class EshpHandler(FileSystemEventHandler):
    def __init__(self, store: EshpStore):
        self.store = store

    def _sync_file(self, path_str: str):
        path = Path(path_str)
        if path.suffix != ".eshp":
            return
        slug = path.stem
        try:
            note = parse_eshp(path)
            self.store.upsert_note(note)
            self.store.conn.commit()
            ts = time.strftime("%H:%M:%S")
            click.echo(f"  {click.style(ts, dim=True)}  {click.style('~', fg='green')} {slug}")
        except Exception as e:
            click.echo(f"  {click.style('!', fg='red')} {slug}: {e}", err=True)

    def _delete_file(self, path_str: str):
        path = Path(path_str)
        if path.suffix != ".eshp":
            return
        slug = path.stem
        self.store.delete_note(slug)
        self.store.conn.commit()
        ts = time.strftime("%H:%M:%S")
        click.echo(f"  {click.style(ts, dim=True)}  {click.style('-', fg='red')} {slug}")

    def on_created(self, event):
        if not event.is_directory:
            self._sync_file(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._sync_file(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self._delete_file(event.src_path)


# ─────────────────────────────────────────────────────────────── CLI commands

@click.group()
def cli():
    """eshp — local agentic memory graph"""
    pass


@cli.command()
@click.option("--root", default=None, type=click.Path(), help="Path to memo folder")
def watch(root):
    """Watch the memo folder and keep the SQLite graph live.

    Does a full sync on startup, then listens for file changes.
    Run this in a background terminal while working.
    """
    store = get_store(Path(root) if root else None)

    # Bootstrap
    click.echo(click.style("eshp watch", bold=True) + f"  {store.root}")
    click.echo()
    n = store.sync(verbose=False)
    click.echo(click.style(f"✓ Bootstrapped {n} note(s)", fg="green"))
    click.echo()
    click.echo(click.style("Watching for changes… (Ctrl-C to stop)", dim=True))
    click.echo()

    handler = EshpHandler(store)
    observer = Observer()
    observer.schedule(handler, str(store.root), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        observer.stop()
        click.echo()
        click.echo(click.style("Stopped.", dim=True))
    finally:
        observer.join()
        store.close()


@cli.command()
@click.argument("slug")
@click.option("--tags", default="", help="Comma-separated tags")
@click.option("--root", default=None, type=click.Path())
def new(slug, tags, root):
    """Create a new .memo note and open it in $EDITOR."""
    store = get_store(Path(root) if root else None)
    path = store.root / f"{slug}.eshp"

    if path.exists():
        click.echo(click.style(f"Note '{slug}' already exists.", fg="yellow"))
        store.close()
        return

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    note = EshpNote(path=path, slug=slug, tags=tag_list, desc="", body="", relationships={})
    path.write_text(render_eshp(note), encoding="utf-8")

    click.echo(click.style(f"→ {path}", dim=True))
    _open_in_editor(path)
    if not (store.root / ".eshp.db").exists() or store.get_note(slug) is None:
        store.sync()
    store.close()


@cli.command()
@click.argument("slug")
@click.option("--root", default=None, type=click.Path())
def show(slug, root):
    """Show a note and its graph edges."""
    store = get_store(Path(root) if root else None)
    note = store.get_note(slug)

    if not note:
        store.close()
        click.echo(click.style(f"Note '{slug}' not found. Is `eshp watch` running?", fg="red"))
        sys.exit(1)

    click.echo()
    click.echo(_note_header(note["slug"], note["tags"] or "", note.get("desc", "")))
    click.echo()

    if note["body"]:
        click.echo(note["body"])
        click.echo()

    if note["edges_out"]:
        out_slugs = [e["dst"] for e in note["edges_out"]]
        descs = store.get_descs(out_slugs)
        click.echo(click.style("Outgoing:", fg="white", bold=True))
        for e in note["edges_out"]:
            click.echo(_edge_line("out", e["rel"], e["dst"], descs.get(e["dst"], "")))
        click.echo()

    if note["edges_in"]:
        in_slugs = [e["src"] for e in note["edges_in"]]
        descs = store.get_descs(in_slugs)
        click.echo(click.style("Incoming:", fg="white", bold=True))
        for e in note["edges_in"]:
            click.echo(_edge_line("in", e["rel"], e["src"], descs.get(e["src"], "")))
        click.echo()

    store.close()


@cli.command()
@click.argument("query")
@click.option("--tag", "-t", multiple=True, help="Filter by tag (repeatable)")
@click.option("--limit", "-n", default=10)
@click.option("--root", default=None, type=click.Path())
def search(query, tag, limit, root):
    """Full-text search across note bodies and slugs."""
    store = get_store(Path(root) if root else None)
    results = store.search(query, tags=list(tag) if tag else None, limit=limit)
    store.close()

    if not results:
        click.echo("No results.")
        return

    click.echo()
    for r in results:
        click.echo(_note_header(r["slug"], r["tags"] or "", r.get("desc", "")))
        if r["body"]:
            preview = r["body"][:120].replace("\n", " ")
            if len(r["body"]) > 120:
                preview += "…"
            click.echo(f"  {preview}")
        click.echo()


@cli.command()
@click.option("--root", default=None, type=click.Path())
def tags(root):
    """List all tags and their note counts."""
    store = get_store(Path(root) if root else None)
    all_tags = store.all_tags()
    store.close()

    if not all_tags:
        click.echo("No tags found.")
        return

    click.echo()
    for tag, cnt in all_tags:
        bar = "█" * min(cnt, 30)
        click.echo(f"  {click.style(f'#{tag}', fg='yellow'):<30} {cnt:3d}  {click.style(bar, fg='blue')}")
    click.echo()


@cli.command()
@click.argument("tagname")
@click.option("--root", default=None, type=click.Path())
def tag(tagname, root):
    """List all notes with a given tag."""
    tagname = tagname.lstrip("#")
    store = get_store(Path(root) if root else None)
    slugs = store.list_by_tag(tagname)

    if not slugs:
        store.close()
        click.echo(f"No notes tagged #{tagname}.")
        return

    descs = store.get_descs(slugs)
    store.close()

    click.echo()
    click.echo(click.style(f"#{tagname}", fg="yellow", bold=True) + f"  ({len(slugs)} notes)")
    for s in slugs:
        desc = descs.get(s, "")
        line = f"  {click.style(s, fg='cyan')}"
        if desc:
            line += f"  {click.style(desc, fg='white', dim=True)}"
        click.echo(line)
    click.echo()


@cli.command()
@click.argument("slug")
@click.option("--depth", "-d", default=1, show_default=True)
@click.option("--rel", default=None, help="Filter by relationship name")
@click.option("--root", default=None, type=click.Path())
def graph(slug, depth, rel, root):
    """Show neighbourhood graph around a note."""
    store = get_store(Path(root) if root else None)
    note = store.get_note(slug)

    if not note:
        click.echo(click.style(f"Note '{slug}' not found.", fg="red"))
        store.close()
        sys.exit(1)

    edges = store.neighbours(slug, rel=rel, depth=depth)

    if not edges:
        store.close()
        click.echo(f"No edges found for '{slug}'.")
        return

    nodes = set()
    for e in edges:
        nodes.add(e["src"])
        nodes.add(e["dst"])

    descs = store.get_descs(list(nodes))
    store.close()

    click.echo()
    click.echo(click.style(f"Graph around: {slug}", bold=True) + f"  (depth={depth})")
    click.echo()

    for e in edges:
        src_desc = descs.get(e["src"], "")
        dst_desc = descs.get(e["dst"], "")
        src_label = e["src"] + (f" ({src_desc})" if src_desc and e["src"] != slug else "")
        dst_label = e["dst"] + (f" ({dst_desc})" if dst_desc and e["dst"] != slug else "")
        src = click.style(src_label, fg="cyan", bold=(e["src"] == slug))
        rel_label = click.style(e["rel"], fg="blue")
        dst = click.style(dst_label, fg="cyan", bold=(e["dst"] == slug))
        click.echo(f"  {src}  --[{rel_label}]-->  {dst}")

    click.echo()
    click.echo(click.style(f"{len(nodes)} node(s), {len(edges)} edge(s)", fg="white", dim=True))
    click.echo()


@cli.command()
@click.option("--root", default=None, type=click.Path())
def stats(root):
    """Show DB statistics."""
    store = get_store(Path(root) if root else None)
    s = store.stats()
    store.close()

    click.echo()
    click.echo(click.style("eshp stats", bold=True))
    click.echo(f"  notes : {click.style(str(s['notes']), fg='cyan')}")
    click.echo(f"  tags  : {click.style(str(s['tags']),  fg='yellow')}")
    click.echo(f"  edges : {click.style(str(s['edges']), fg='green')}")
    click.echo()


if __name__ == "__main__":
    cli()
