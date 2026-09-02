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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from . import ids, store

#: A concept id is a path fragment, and it arrives from model output.
_SAFE_CONCEPT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$")


class AugmentationError(ValueError):
    """A write would shrink an existing concept. Fix it and retry - do not force it."""


class LifecycleError(ValueError):
    """A concept type with no declared lifecycle. Add it to LIFECYCLE, do not bypass."""


@dataclass(frozen=True)
class Lifecycle:
    """How one concept type ages, and which part of it does not.

    OKF leaves `stale_after` to the implementer and says so plainly: *"who sets
    it, and to what, is the one decision that determines whether a wiki decays
    gracefully or noisily."* This table is that decision, made once per type
    rather than at each call site.

    `durable_section` is the heading whose content does NOT perish. A company
    dossier's "what it is" is true next month; its "bull case" is a snapshot of
    a tape that has already moved. Splitting them is what lets a stale document
    stay useful instead of having to be excluded or deleted - which matters
    because the muse's whole mandate is colliding unrelated CONCEPTS, and a
    concept does not go stale just because a price did.
    """

    #: Hours before the perishable content should be read as history, not news.
    #: None means the type is timeless (a technique, a lesson).
    perishable_after_hours: int | None
    #: Heading whose body survives expiry. None means "the whole document is
    #: durable" for a timeless type, or "all of it perishes" for a dated one.
    durable_section: str | None = None
    #: May housekeeping tombstone instances of this type once expired? False
    #: for singletons that rewrite themselves (context/regime) - there is no
    #: accumulation to sweep, and deprecating the only copy is just noise.
    sweepable: bool = False


#: The registry. **A type absent from here cannot be written** - that refusal is
#: the mechanism that keeps a new document type from repeating this whole story.
#: `Position` is deliberately not listed: position pages have their own status
#: machine and never go through `write_concept` (D-023).
LIFECYCLE: dict[str, Lifecycle] = {
    "CompanyDossier": Lifecycle(24, durable_section="What it is", sweepable=True),
    "MarketContext": Lifecycle(24),
    "Technique": Lifecycle(None),
    "Lesson": Lifecycle(None),
}


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

    def section(self, heading: str) -> str:
        """The body under one `# heading`, or "" if absent.

        Matches at any heading depth and stops at the next heading of any
        depth, so it reads the same document the augmentation guard protects.
        """
        pattern = rf"^#{{1,6}}\s+{re.escape(heading)}\s*$\n(.*?)(?=^#{{1,6}}\s|\Z)"
        m = re.search(pattern, self.body, re.DOTALL | re.MULTILINE)
        return m.group(1).strip() if m else ""

    def durable_text(self) -> str:
        """The part of this concept that does not perish - for readers that
        want the CONCEPT rather than the snapshot.

        Falls back to the whole body when the type declares no durable section
        or the section is missing/empty: a partially-written document should
        degrade to "everything", never to "nothing", or a consumer silently
        loses the page instead of losing its freshness.
        """
        policy = LIFECYCLE.get(self.type)
        if policy and policy.durable_section:
            text = self.section(policy.durable_section)
            if text:
                return text
        return self.body.strip()

    def is_stale(self, now: datetime | None = None) -> bool:
        """Has the perishable content passed its expiry?

        Falls back to `generated.at + perishable_after_hours` when no
        `stale_after` is stamped. Without that fallback the 24 dossiers written
        before lifecycle stamping landed were permanently un-sweepable and
        permanently eligible as muse collision material - fail-safe at the time
        it shipped, but the safety never expired (I-20).
        """
        raw = self.frontmatter.get("stale_after")
        if not raw:
            policy = LIFECYCLE.get(self.type)
            generated = (self.frontmatter.get("generated") or {}).get("at")
            if not policy or policy.perishable_after_hours is None or not generated:
                return False
            try:
                born = datetime.fromisoformat(str(generated).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                return False
            if born.tzinfo is None:
                born = born.replace(tzinfo=UTC)
            deadline = born + timedelta(hours=policy.perishable_after_hours)
            return (now or ids.utc_now()) >= deadline
        try:
            when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return False
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return (now or ids.utc_now()) >= when

    def add_source(self, resource: str, *, author: str = "", id_: str | None = None) -> str:
        """Record a source, or refresh one already recorded.

        Deliberately keyed on (resource, author), NOT on a generated id. The
        old form minted `src-{len+1}` every call, so the id was new every time
        and the entry always appended - `research/NVDA.md` carries four
        identical `computed:market_stats` rows, one per research pass, growing
        without bound. Four copies of one source are not four credibility
        signals; OKF's signal is `last_modified`, and refreshing it in place is
        what that field is for.

        Existing duplicates are left alone rather than compacted: the
        augmentation guard refuses any write that shrinks `sources`, so a
        retroactive dedupe would be rejected by our own rule. The bloat stops
        growing, which is the part that mattered.
        """
        sources: list[dict[str, Any]] = self.frontmatter.setdefault("sources", [])
        if id_ is None:
            for s in sources:
                if s.get("resource") == resource and s.get("author", "") == author:
                    s["last_modified"] = ids.utc_now().isoformat()
                    return str(s.get("id", ""))
        sid = id_ or f"src-{len(sources) + 1}"
        if not any(s.get("id") == sid for s in sources):
            sources.append({
                "id": sid, "resource": resource, "author": author,
                "last_modified": ids.utc_now().isoformat(),
            })
        return sid


class Wiki:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, concept_id: str) -> Path:
        """The file for a concept id, refusing anything that escapes the root.

        Concept ids are built from MODEL OUTPUT - `f"research/{ticker}"` where
        the ticker came back from an LLM - so this is a boundary, and
        validating at a boundary is the fail-fast rule rather than defensive
        code. Without it a key containing `..` writes outside the wiki
        entirely.
        """
        if not _SAFE_CONCEPT_ID.match(concept_id) or ".." in concept_id.split("/"):
            raise ValueError(
                f"unsafe concept id {concept_id!r}: expected path-like segments of "
                f"letters, digits, dot, dash or underscore - no absolute paths, no `..`"
            )
        return self.root / f"{concept_id}.md"

    def read(self, concept_id: str) -> Concept | None:
        p = self.path_for(concept_id)
        if not p.exists():
            return None
        return self._parse(p, concept_id)

    def _parse(self, path: Path, concept_id: str) -> Concept:
        """Parse a page, degrading rather than raising on a malformed one.

        `text.split("---", 2)` unpacking three values raised ValueError on a
        file with unterminated frontmatter - and `read()` is on the hot path
        (the decide prompt's regime block, every dossier lookup) with no guard,
        while `all_concepts` already caught per-page. One truncated write and
        the tick died reading its own wiki.
        """
        text = path.read_text(encoding="utf-8")
        fm: dict[str, Any] = {}
        body = text
        try:
            # THE FENCE, not the substring - the same helper `positions._parse`
            # uses, because this had the identical bug (I-123): a
            # `sources[].resource` or a title containing ` --- ` lost every
            # later frontmatter key, and for a POSITION page `attribution.run`
            # then marked the truncated result unscoreable and saved it back.
            fm_text, body = store.split_frontmatter(text)
            loaded = yaml.safe_load(fm_text) if fm_text else None
            fm = loaded if isinstance(loaded, dict) else {}
        except (ValueError, yaml.YAMLError) as exc:
            print(f"[wiki] {concept_id}: unreadable frontmatter ({exc!r}) - "
                  f"reading the whole file as body")
            fm, body = {}, text
        return Concept(concept_id=concept_id, frontmatter=fm, body=body.strip() + "\n", path=path)

    def write_concept(self, concept: Concept, *, type_: str | None = None,
                      touch_generated: bool = True) -> Path:
        """Write with the monotonic-augmentation guard (D-023) and the lifecycle guard.

        A write that would shrink `sources`/`tags`, or drop a heading present in
        the prior version, is refused. Callers must merge, not replace. This is
        deliberately strict: a rejected write means "fix it and retry", not
        "silently lose what was there".

        **The lifecycle guard is the second half of that idea.** A type with no
        entry in `LIFECYCLE` cannot be written at all, so a new document type
        must say how it ages before it can exist - which is what stops the
        research-dossier story repeating. Freshness is then stamped from the
        policy rather than by each call site, because a per-caller `stale_after`
        is how two writers of the same file end up disagreeing about when it
        expires.

        `touch_generated=False` is for writes that change a document's STATUS
        without regenerating it - a housekeeping tombstone must not leave the
        page looking freshly researched.
        """
        if type_:
            concept.frontmatter["type"] = type_
        if "type" not in concept.frontmatter:
            raise ValueError(f"{concept.concept_id}: OKF requires a `type` field")

        policy = LIFECYCLE.get(concept.frontmatter["type"])
        if policy is None:
            raise LifecycleError(
                f"{concept.concept_id}: type {concept.frontmatter['type']!r} has no "
                f"lifecycle. Add it to wiki.LIFECYCLE saying how it ages - whether its "
                f"content perishes, which heading survives, and whether housekeeping may "
                f"tombstone it. Known types: {sorted(LIFECYCLE)}."
            )

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

        if touch_generated:
            concept.frontmatter.setdefault("generated", {})["at"] = ids.utc_now().isoformat()
            # Freshness comes from the policy, once, so two writers of one file
            # cannot disagree about when it expires. A write is also a REVIVAL:
            # re-researching a tombstoned dossier makes it current again, and
            # leaving `deprecated` on a page we just rewrote would be a lie.
            if policy.perishable_after_hours is not None:
                concept.frontmatter["stale_after"] = (
                    ids.utc_now() + timedelta(hours=policy.perishable_after_hours)
                ).isoformat()
                concept.frontmatter["status"] = "stable"
        fm_text = yaml.safe_dump(concept.frontmatter, sort_keys=False)
        path = self.path_for(concept.concept_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        store.write_atomic(path, f"---\n{fm_text}---\n\n{concept.body}")
        concept.path = path
        return path

    def all_concepts(self, subdir: str = "") -> list[Concept]:
        """Every readable concept, optionally under one subdirectory."""
        root = self.root / subdir if subdir else self.root
        out: list[Concept] = []
        for p in sorted(root.rglob("*.md")):
            if p.name in ("log.md",) or p.name.endswith(".history.md") or "positions/" in str(p):
                continue
            cid = str(p.relative_to(self.root)).removesuffix(".md")
            try:
                out.append(self._parse(p, cid))
            except Exception as exc:  # noqa: BLE001 - one bad page must not stop a sweep
                print(f"[wiki] skipping unreadable {p.name}: {exc!r}")
        return out

    def sweep(self, *, protected: set[str] | None = None,
              now: datetime | None = None) -> dict[str, list[str]]:
        """Tombstone expired concepts. **Marks, never deletes, never moves.**

        Deletion is refused on principle and archiving-by-move is refused on
        mechanics. OKF's own answer to a dead concept is `status: deprecated`,
        tombstone-in-place, and everything else in this system is append-only -
        the journal, the ledger, position pages. A file that moves can be missed
        mid-read by a concurrent consumer; a frontmatter flag cannot, and the
        page stays where anyone looking for it will look.

        `protected` is the set of concept ids that must survive whatever their
        age - the underlyings we currently hold. A position outlives the
        research cadence, and tombstoning the only page explaining why we are
        in a trade would be the worst possible moment to do it.

        Reversible by construction: re-researching a ticker rewrites the page,
        and `write_concept` restores `status: stable` on the way through.
        """
        protected = protected or set()
        marked, skipped = [], []
        for c in self.all_concepts():
            policy = LIFECYCLE.get(c.type)
            if not policy or not policy.sweepable:
                continue
            if not c.is_stale(now):
                continue
            if c.frontmatter.get("status") == "deprecated":
                continue  # already tombstoned; do not re-stamp
            if c.concept_id in protected:
                skipped.append(c.concept_id)
                continue
            c.frontmatter["status"] = "deprecated"
            # touch_generated=False: a tombstone is not a regeneration, and a
            # swept page must not come out looking freshly researched.
            self.write_concept(c, touch_generated=False)
            marked.append(c.concept_id)
        return {"deprecated": marked, "protected": skipped}

    def archive_prior(self, concept: Concept) -> bool:
        """Keep the page's CURRENT body before it is overwritten (D-110).

        A page is never deleted - the sweep tombstones in place - but it IS
        overwritten: research rewrites `context/regime` every morning, handing
        the model yesterday's text to "update, not rewrite from scratch". The
        previous assessment then existed only in git, and only when a human
        committed `data/`, which the loop never does. Between commits each
        rewrite destroyed the prior one - and the regime page is the one
        surface from which "how regimes change" could ever be learned.

        Prepended under a dated heading to `<concept_id>.history.md`, newest
        first, the same shape as `log.md`. Not a Concept: `all_concepts`
        excludes it, so the muse cannot sample a history as an idea.
        Returns False when there is nothing to keep (an empty page).
        """
        if not concept.body.strip():
            return False
        path = self.root / f"{concept.concept_id}.history.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        today = ids.utc_now().strftime("%Y-%m-%d")
        prior = path.read_text(encoding="utf-8") if path.exists() else ""
        store.write_atomic(path, f"## {today}\n\n{concept.body.rstrip()}\n\n{prior}")
        return True

    def append_log(self, entry: str, *, dir_: Path | None = None) -> None:
        """OKF log.md: newest-first, dated headings (D-022's reserved filename)."""
        log_path = (dir_ or self.root) / "log.md"
        today = ids.utc_now().strftime("%Y-%m-%d")
        line = f"- {entry}\n"
        if log_path.exists():
            text = log_path.read_text(encoding="utf-8")
            heading = f"## {today}\n"
            if text.startswith(heading):
                store.write_atomic(log_path, text.replace(heading, heading + line, 1))
                return
        else:
            text = ""
        store.write_atomic(log_path, f"## {today}\n{line}\n{text}")
