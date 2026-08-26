"""OKF-conventioned wiki reads/writes (D-022, D-023).

Every concept file gets `type:` (the only field OKF requires), `sources[]` with
footnote-keyed attribution, `generated`/`verified` trust tiers, and
`status`/`stale_after` where freshness matters (context/*.md).

The load-bearing piece is `write_concept`'s augmentation guard (D-023): this is
the actual mechanism against an LLM-maintained wiki quietly degrading. Writes
are full-replacement, and a write that would shrink `sources`/`tags` or drop a
heading that already existed is refused outright rather than silently losing
what was there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import ids


class AugmentationError(ValueError):
    """A write would shrink an existing concept. Fix it and retry - do not force it."""


@dataclass
class Concept:
    concept_id: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    path: Path | None = None

    @property
    def type(self) -> str:
        return self.frontmatter.get("type", "")

    def headings(self) -> list[str]:
        return re.findall(r"^#{1,6}\s+.*$", self.body, re.MULTILINE)

    def add_source(self, resource: str, *, author: str = "", id_: str | None = None) -> str:
        sources: list[dict[str, Any]] = self.frontmatter.setdefault("sources", [])
        sid = id_ or f"src-{len(sources) + 1}"
        if not any(s.get("id") == sid for s in sources):
            sources.append({
                "id": sid, "resource": resource, "author": author,
                "last_modified": ids.utc_now().isoformat(),
            })
        return sid

    def verify(self, by: str) -> None:
        """Append a verification event -> promotes trust tier (D-022)."""
        self.frontmatter.setdefault("verified", []).append(
            {"by": by, "at": ids.utc_now().isoformat()}
        )

    def trust_tier(self) -> str:
        verified = self.frontmatter.get("verified") or []
        if not verified:
            return "unverified"
        if any(str(v.get("by", "")).startswith("human:") for v in verified):
            return "human-reviewed"
        return "machine-confirmed"


class Wiki:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, concept_id: str) -> Path:
        return self.root / f"{concept_id}.md"

    def read(self, concept_id: str) -> Concept | None:
        p = self.path_for(concept_id)
        if not p.exists():
            return None
        return self._parse(p, concept_id)

    def _parse(self, path: Path, concept_id: str) -> Concept:
        text = path.read_text()
        if text.startswith("---"):
            _, fm_text, body = text.split("---", 2)
            fm = yaml.safe_load(fm_text) or {}
        else:
            fm, body = {}, text
        return Concept(concept_id=concept_id, frontmatter=fm, body=body.strip() + "\n", path=path)

    def write_concept(self, concept: Concept, *, type_: str | None = None) -> Path:
        """Write with the monotonic-augmentation guard (D-023).

        A write that would shrink `sources`/`tags`, or drop a heading present in
        the prior version, is refused. Callers must merge, not replace. This is
        deliberately strict: a rejected write means "fix it and retry", not
        "silently lose what was there".
        """
        if type_:
            concept.frontmatter["type"] = type_
        if "type" not in concept.frontmatter:
            raise ValueError(f"{concept.concept_id}: OKF requires a `type` field")

        existing = self.read(concept.concept_id)
        if existing:
            for key in ("sources", "tags"):
                before, after = existing.frontmatter.get(key) or [], concept.frontmatter.get(key) or []
                if len(after) < len(before):
                    raise AugmentationError(
                        f"{concept.concept_id}: write would shrink `{key}` "
                        f"({len(before)} -> {len(after)}). Union-merge instead of replacing."
                    )
            missing = [h for h in existing.headings() if h not in concept.headings()]
            if missing:
                raise AugmentationError(
                    f"{concept.concept_id}: write drops existing heading(s) {missing}. "
                    f"Extend the document, don't replace sections."
                )

        concept.frontmatter.setdefault("generated", {})["at"] = ids.utc_now().isoformat()
        fm_text = yaml.safe_dump(concept.frontmatter, sort_keys=False)
        path = self.path_for(concept.concept_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\n{fm_text}---\n\n{concept.body}")
        concept.path = path
        return path

    def append_log(self, entry: str, *, dir_: Path | None = None) -> None:
        """OKF log.md: newest-first, dated headings (D-022's reserved filename)."""
        log_path = (dir_ or self.root) / "log.md"
        today = ids.utc_now().strftime("%Y-%m-%d")
        line = f"- {entry}\n"
        if log_path.exists():
            text = log_path.read_text()
            heading = f"## {today}\n"
            if text.startswith(heading):
                log_path.write_text(text.replace(heading, heading + line, 1))
                return
        else:
            text = ""
        log_path.write_text(f"## {today}\n{line}\n{text}")


def should_mint(*, is_referenceable: bool, is_bundle_meta: bool, has_citation_sentence: bool,
                reuse_count: int, is_load_bearing: bool = False) -> bool:
    """The four-gate mint test (D-023, borrowed from OKF's reference agent).

    Gate 4 (reuse) passes if >=2 existing concepts would cite this, OR it is
    load-bearing background for at least one. All four gates must pass. When
    in doubt, don't mint - a wiki full of one-off observations is noise, not
    knowledge.
    """
    gate4 = reuse_count >= 2 or is_load_bearing
    return is_referenceable and not is_bundle_meta and has_citation_sentence and gate4
