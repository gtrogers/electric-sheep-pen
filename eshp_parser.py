"""
Parser for .eshp files.

Format:
  #tag1 #tag2

  Free text body here

  .relationship-name
  -> other-file
  -> other-file
  <- other-file

  .another-relationship
  -> other-file
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Relationship:
    name: str
    outgoing: list[str] = field(default_factory=list)  # ->
    incoming: list[str] = field(default_factory=list)  # <-


@dataclass
class EshpNote:
    path: Path
    slug: str          # filename without extension
    tags: list[str]
    body: str
    relationships: dict[str, Relationship]  # name -> Relationship

    @property
    def all_outgoing(self) -> list[tuple[str, str]]:
        """All (rel_name, target_slug) outgoing edges."""
        edges = []
        for rel in self.relationships.values():
            for t in rel.outgoing:
                edges.append((rel.name, t))
        return edges

    @property
    def all_incoming(self) -> list[tuple[str, str]]:
        """All (rel_name, source_slug) incoming edges declared in this file."""
        edges = []
        for rel in self.relationships.values():
            for s in rel.incoming:
                edges.append((rel.name, s))
        return edges


def parse_eshp(path: Path) -> EshpNote:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    tags: list[str] = []
    body_lines: list[str] = []
    relationships: dict[str, Relationship] = {}
    current_rel: Optional[Relationship] = None

    # First non-empty line(s) starting with # are the tag line
    tag_section_done = False

    for line in lines:
        stripped = line.strip()

        # Tag line: starts with # tokens
        if not tag_section_done:
            if stripped == "":
                if tags:
                    tag_section_done = True
                continue
            tag_tokens = re.findall(r"#(\S+)", stripped)
            if tag_tokens and all(t.startswith("#") or re.match(r"#\S+", stripped) for t in tag_tokens):
                tags.extend(tag_tokens)
                continue
            else:
                tag_section_done = True
                # Fall through to body/rel handling

        # Relationship section header
        if stripped.startswith(".") and not stripped.startswith(".."):
            rel_name = stripped[1:].strip()
            current_rel = Relationship(name=rel_name)
            relationships[rel_name] = current_rel
            continue

        # Relationship edges
        if current_rel is not None:
            if stripped.startswith("->"):
                target = stripped[2:].strip()
                if target:
                    current_rel.outgoing.append(target)
                continue
            elif stripped.startswith("<-"):
                source = stripped[2:].strip()
                if source:
                    current_rel.incoming.append(source)
                continue
            elif stripped == "":
                # blank line ends relationship block
                current_rel = None
                continue
            else:
                # non-edge content: back to body
                current_rel = None

        # Body text
        body_lines.append(line)

    body = "\n".join(body_lines).strip()
    slug = path.stem

    return EshpNote(
        path=path,
        slug=slug,
        tags=tags,
        body=body,
        relationships=relationships,
    )


def render_eshp(note: EshpNote) -> str:
    """Render an EshpNote back to the .eshp file format."""
    parts = []

    if note.tags:
        parts.append(" ".join(f"#{t}" for t in note.tags))
        parts.append("")

    if note.body:
        parts.append(note.body)
        parts.append("")

    for rel in note.relationships.values():
        parts.append(f".{rel.name}")
        for t in rel.outgoing:
            parts.append(f"-> {t}")
        for s in rel.incoming:
            parts.append(f"<- {s}")
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"
