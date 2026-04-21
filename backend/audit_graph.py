"""
Knowledge-graph audit (Phase A — read-only).

Produces an actionable anomaly report over the serialized KG
(``vector_db_qdrant/knowledge_graph.json``) and the scraped page corpus
under ``backend/data/srm_docs/``. Writes to ``backend/audit/``.

Five sections, each feeding a specific Phase B fix:

  §1 Admissions with no outgoing ``admission_governs`` and
     no ``admission_covers`` edges.
  §2 Programs with no inbound ``admission_governs`` edges,
     grouped by parent department.
  §3 Centres whose primary ``has_centre`` parent disagrees with the
     department/college pages that actually link to them on the
     scraped site.
  §4 Centre nodes whose name has no centre/lab/facility-style token —
     likely misclassified events, workshops, or misc content.
  §5 Centre/lab nodes whose ``url`` has no scraped folder, or whose
     scraped ``content.txt`` is thin (< 200 chars).

Usage:
    python -m backend.audit_graph
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
GRAPH_PATH = REPO_ROOT / "vector_db_qdrant" / "knowledge_graph.json"
DOCS_ROOT = REPO_ROOT / "backend" / "data" / "srm_docs"
AUDIT_DIR = REPO_ROOT / "backend" / "audit"

CENTRE_NAME_TOKENS = (
    "centre", "center", "lab", "laboratory", "cdc", "platform",
    "institute", "chair", "facility", "excellence", "cell", "hub",
    "studio", "observatory", "museum", "workshop", "incubator",
    "clinic", "garden", "greenhouse",
)
# Tokens that indicate misc/event/outreach, not a centre.
NON_CENTRE_NAME_TOKENS = (
    "extension activities", "community outreach", "outreach program",
    "events", "clinical departments",
)
# Tokens that suggest the node is really a facility (workshop/shop/etc.),
# not a research/academic centre.
FACILITY_NAME_TOKENS = (
    "shop", "yard", "hangar", "hall", "suite", "gallery", "garage",
)

THIN_CONTENT_CHARS = 200


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_url(url: str | None) -> str:
    if not url:
        return ""
    return url.strip().rstrip("/").lower()


def _load_graph() -> dict:
    with GRAPH_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _build_scraped_index() -> dict[str, Path]:
    """Map normalized URL -> page folder by scanning every metadata.json."""
    index: dict[str, Path] = {}
    if not DOCS_ROOT.exists():
        return index
    for folder in DOCS_ROOT.iterdir():
        if not folder.is_dir():
            continue
        meta_path = folder / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            with meta_path.open("r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        url = _normalize_url(meta.get("url"))
        if url:
            index[url] = folder
    return index


def _internal_links(folder: Path) -> list[str]:
    meta_path = folder / "metadata.json"
    if not meta_path.exists():
        return []
    try:
        with meta_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    links = meta.get("internal_links") or []
    return [_normalize_url(l) for l in links if isinstance(l, str)]


def _read_content(folder: Path) -> str:
    path = folder / "content.txt"
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _entity_url(entity: dict) -> str:
    return _normalize_url(entity.get("url"))


def _parents_by_relation(
    relationships: list[dict],
    target_type: str,
) -> dict[str, list[str]]:
    """Return {child_id: [parent_id, ...]} for the given relation."""
    out: dict[str, list[str]] = defaultdict(list)
    for rel in relationships:
        if rel.get("relation_type") == target_type:
            out[rel["target_id"]].append(rel["source_id"])
    return out


def _children_by_relation(
    relationships: list[dict],
    target_type: str,
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for rel in relationships:
        if rel.get("relation_type") == target_type:
            out[rel["source_id"]].append(rel["target_id"])
    return out


def _name_has_centre_token(name: str) -> bool:
    low = (name or "").lower()
    if any(tok in low for tok in NON_CENTRE_NAME_TOKENS):
        return False
    return any(tok in low for tok in CENTRE_NAME_TOKENS)


def _suggest_reclassification(name: str, url: str) -> str:
    low = (name or "").lower()
    u = (url or "").lower()
    if any(tok in low for tok in NON_CENTRE_NAME_TOKENS):
        return "misc"
    if any(tok in low for tok in FACILITY_NAME_TOKENS):
        return "facility"
    if "/lab/" in u and not any(tok in low for tok in CENTRE_NAME_TOKENS):
        return "facility"
    return "misc"


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _section_1_isolated_admissions(
    entities: dict[str, dict],
    relationships: list[dict],
) -> list[dict]:
    governs_src = {r["source_id"] for r in relationships if r["relation_type"] == "admission_governs"}
    covers_src = {r["source_id"] for r in relationships if r["relation_type"] == "admission_covers"}
    out = []
    for eid, e in entities.items():
        if e.get("entity_type") != "admission":
            continue
        if eid in governs_src or eid in covers_src:
            continue
        out.append({
            "admission_id": eid,
            "name": e.get("name"),
            "url": e.get("url"),
            "scope_slug": (e.get("attributes") or {}).get("scope_slug"),
        })
    return out


def _section_2_unlinked_programs(
    entities: dict[str, dict],
    relationships: list[dict],
) -> list[dict]:
    governs_tgt = {r["target_id"] for r in relationships if r["relation_type"] == "admission_governs"}
    offers_parents = _parents_by_relation(relationships, "offers_program")
    out = []
    for eid, e in entities.items():
        if e.get("entity_type") != "program":
            continue
        if eid in governs_tgt:
            continue
        parents = offers_parents.get(eid, [])
        parent_names = [entities.get(p, {}).get("name", p) for p in parents]
        out.append({
            "program_id": eid,
            "name": e.get("name"),
            "url": e.get("url"),
            "parents": parents,
            "parent_names": parent_names,
        })
    return out


def _section_3_centre_parent_mismatch(
    entities: dict[str, dict],
    relationships: list[dict],
    scraped_index: dict[str, Path],
) -> list[dict]:
    # Current primary parent (from has_centre).
    has_centre_parents = _parents_by_relation(relationships, "has_centre")

    dept_like_types = {"department", "sub_college", "college", "directorate", "school"}
    # dept_url -> dept_eid, so we can assign sub-pages to the nearest dept.
    dept_url_to_eid: dict[str, str] = {}
    for eid, e in entities.items():
        if e.get("entity_type") in dept_like_types:
            url = _entity_url(e)
            if url:
                dept_url_to_eid[url] = eid

    def _owning_dept(url: str) -> str | None:
        """Longest-prefix match: which dept/college URL is this page under?"""
        if not url:
            return None
        best: tuple[int, str | None] = (0, None)
        for d_url, d_eid in dept_url_to_eid.items():
            if url == d_url or url.startswith(d_url.rstrip("/") + "/"):
                if len(d_url) > best[0]:
                    best = (len(d_url), d_eid)
        return best[1]

    # Aggregate internal_links from every scraped page, attributing each to
    # the dept/college whose URL is the longest prefix of that page's URL.
    link_observers: dict[str, set[str]] = defaultdict(set)
    for page_url, folder in scraped_index.items():
        dept_eid = _owning_dept(page_url)
        if not dept_eid:
            continue
        for link in _internal_links(folder):
            if "/lab/" in link or "/centre/" in link or "/center/" in link \
                    or "/department/" in link:
                link_observers[link].add(dept_eid)

    # Structural containment: ancestors[eid] = set of entities that contain eid
    containment_relations = {
        "has_college", "has_sub_college", "has_department",
        "has_directorate", "has_school", "has_centre",
    }
    ancestors: dict[str, set[str]] = defaultdict(set)
    for rel in relationships:
        if rel.get("relation_type") in containment_relations:
            ancestors[rel["target_id"]].add(rel["source_id"])
    # Transitive closure (small graph — naive fixpoint is fine).
    changed = True
    while changed:
        changed = False
        for child, parents in list(ancestors.items()):
            grand = set()
            for p in parents:
                grand |= ancestors.get(p, set())
            new = parents | grand
            if new != parents:
                ancestors[child] = new
                changed = True

    out = []
    for eid, e in entities.items():
        if e.get("entity_type") != "centre":
            continue
        centre_url = _entity_url(e)
        current_parents = has_centre_parents.get(eid, [])
        current_primary = current_parents[0] if current_parents else None
        observed = sorted(link_observers.get(centre_url, set()))
        if not observed:
            continue
        if current_primary in observed:
            continue
        # Skip if current parent is a descendant of any observed parent
        # (finer-grained correct placement, e.g. a sub-dept listed under its
        # parent college's page).
        if current_primary and any(
            obs in ancestors.get(current_primary, set()) for obs in observed
        ):
            continue
        out.append({
            "centre_id": eid,
            "centre_name": e.get("name"),
            "centre_url": e.get("url"),
            "current_parent": current_primary,
            "current_parent_name": (
                entities.get(current_primary, {}).get("name") if current_primary else None
            ),
            "observed_parents": observed,
            "observed_parent_names": [
                entities.get(p, {}).get("name", p) for p in observed
            ],
        })
    return out


def _section_4_suspected_non_centres(
    entities: dict[str, dict],
) -> list[dict]:
    out = []
    for eid, e in entities.items():
        if e.get("entity_type") != "centre":
            continue
        name = e.get("name", "")
        low = name.lower()
        if any(tok in low for tok in NON_CENTRE_NAME_TOKENS):
            out.append({
                "centre_id": eid,
                "name": name,
                "url": e.get("url"),
                "suggested_type": _suggest_reclassification(name, e.get("url", "")),
                "reason": "non-centre token in name",
            })
            continue
        if not _name_has_centre_token(name):
            out.append({
                "centre_id": eid,
                "name": name,
                "url": e.get("url"),
                "suggested_type": _suggest_reclassification(name, e.get("url", "")),
                "reason": "no centre/lab/facility token in name",
            })
    return out


def _section_5_dead_pages(
    entities: dict[str, dict],
    relationships: list[dict],
    scraped_index: dict[str, Path],
) -> list[dict]:
    # Which centre URLs are linked from some dept/college page or a
    # sub-page thereof? Used to decide whether to detach or just warn.
    dept_like_types = {"department", "sub_college", "college", "directorate", "school"}
    dept_urls = {
        _entity_url(e)
        for e in entities.values()
        if e.get("entity_type") in dept_like_types and e.get("url")
    }
    dept_urls.discard("")
    referenced_urls: set[str] = set()
    for page_url, folder in scraped_index.items():
        if not any(
            page_url == d or page_url.startswith(d.rstrip("/") + "/")
            for d in dept_urls
        ):
            continue
        for link in _internal_links(folder):
            referenced_urls.add(link)

    out = []
    for eid, e in entities.items():
        if e.get("entity_type") != "centre":
            continue
        url = _entity_url(e)
        if not url:
            out.append({
                "centre_id": eid, "name": e.get("name"),
                "url": "", "status": "no_url",
                "listed_on_dept_page": False,
            })
            continue
        folder = scraped_index.get(url)
        if folder is None:
            out.append({
                "centre_id": eid, "name": e.get("name"),
                "url": e.get("url"),
                "status": "no_scraped_folder",
                "listed_on_dept_page": url in referenced_urls,
            })
            continue
        content = _read_content(folder)
        if len(content) < THIN_CONTENT_CHARS:
            out.append({
                "centre_id": eid, "name": e.get("name"),
                "url": e.get("url"),
                "status": "thin_content",
                "content_chars": len(content),
                "listed_on_dept_page": url in referenced_urls,
            })
    return out


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------

def _write_markdown(path: Path, sections: dict[str, list[dict]]) -> None:
    lines: list[str] = []
    lines.append("# Knowledge Graph Audit Report")
    lines.append("")
    lines.append(f"- Graph: `{GRAPH_PATH.relative_to(REPO_ROOT)}`")
    lines.append(f"- Scraped docs: `{DOCS_ROOT.relative_to(REPO_ROOT)}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    for key, rows in sections.items():
        lines.append(f"- **§ {key}** — {len(rows)} row(s)")
    lines.append("")

    def _tbl(headers: list[str], rows: Iterable[list[str]]) -> None:
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join("---" for _ in headers) + "|")
        for r in rows:
            lines.append("| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |")
        lines.append("")

    # §1
    lines.append("## §1 Admissions with no program or scope links")
    lines.append("")
    s1 = sections["1_isolated_admissions"]
    if s1:
        _tbl(
            ["admission_id", "name", "scope_slug", "url"],
            [[r["admission_id"], r["name"], r.get("scope_slug") or "", r.get("url") or ""] for r in s1],
        )
    else:
        lines.append("_none_\n")

    # §2
    lines.append("## §2 Programs with no `admission_governs` edge")
    lines.append("")
    s2 = sections["2_unlinked_programs"]
    lines.append(f"_Total: {len(s2)}_\n")
    by_parent = defaultdict(list)
    for r in s2:
        key = ", ".join(r["parent_names"]) or "(no parent)"
        by_parent[key].append(r)
    for parent, rows in sorted(by_parent.items()):
        lines.append(f"### Parent: {parent} ({len(rows)})")
        lines.append("")
        _tbl(
            ["program_id", "name"],
            [[r["program_id"], r["name"]] for r in rows],
        )

    # §3
    lines.append("## §3 Centres with mismatched primary parent")
    lines.append("")
    s3 = sections["3_centre_parent_mismatch"]
    if s3:
        _tbl(
            ["centre_id", "current_parent", "observed_parents", "centre_url"],
            [[
                r["centre_id"],
                r.get("current_parent_name") or r.get("current_parent") or "(none)",
                "; ".join(r["observed_parent_names"]),
                r.get("centre_url") or "",
            ] for r in s3],
        )
    else:
        lines.append("_none_\n")

    # §4
    lines.append("## §4 Suspected non-centres (mis-typed as centre)")
    lines.append("")
    s4 = sections["4_suspected_non_centres"]
    if s4:
        _tbl(
            ["centre_id", "name", "suggested_type", "reason", "url"],
            [[r["centre_id"], r["name"], r["suggested_type"], r["reason"], r.get("url") or ""] for r in s4],
        )
    else:
        lines.append("_none_\n")

    # §5
    lines.append("## §5 Dead / thin centre pages")
    lines.append("")
    s5 = sections["5_dead_pages"]
    if s5:
        _tbl(
            ["centre_id", "name", "status", "listed_on_dept_page", "url"],
            [[
                r["centre_id"], r.get("name", ""), r["status"],
                "yes" if r.get("listed_on_dept_page") else "no",
                r.get("url") or "",
            ] for r in s5],
        )
    else:
        lines.append("_none_\n")

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    graph = _load_graph()
    entities: dict[str, dict] = graph["entities"]
    relationships: list[dict] = graph["relationships"]
    scraped_index = _build_scraped_index()

    sections = {
        "1_isolated_admissions": _section_1_isolated_admissions(entities, relationships),
        "2_unlinked_programs": _section_2_unlinked_programs(entities, relationships),
        "3_centre_parent_mismatch": _section_3_centre_parent_mismatch(
            entities, relationships, scraped_index,
        ),
        "4_suspected_non_centres": _section_4_suspected_non_centres(entities),
        "5_dead_pages": _section_5_dead_pages(entities, relationships, scraped_index),
    }

    json_path = AUDIT_DIR / "graph_audit.json"
    md_path = AUDIT_DIR / "graph_audit.md"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(sections, f, indent=2, ensure_ascii=False)
    _write_markdown(md_path, sections)

    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    for key, rows in sections.items():
        print(f"  §{key}: {len(rows)}")


if __name__ == "__main__":
    main()
