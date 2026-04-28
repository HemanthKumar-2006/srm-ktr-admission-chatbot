"""
Program Reconciliation Script
==============================

Reconciles the Knowledge Graph program catalog with the authoritative
SRM Program Finder CSV (srm_programs_clean.csv).

Usage:
    python "Programs Helper/reconcile_programs.py"                # Dry-run: report only
    python "Programs Helper/reconcile_programs.py" --apply        # Apply fixes

Outputs:
    - Programs Helper/reconciliation_report.md   (always)
    - vector_db_qdrant/knowledge_graph.json      (only with --apply)
    - vector_db_qdrant/knowledge_graph.js         (only with --apply)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

# ---- Paths ----
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
KG_JSON_PATH = PROJECT_ROOT / "vector_db_qdrant" / "knowledge_graph.json"
KG_JS_PATH = PROJECT_ROOT / "vector_db_qdrant" / "knowledge_graph.js"
CSV_PATH = SCRIPT_DIR / "srm_programs_clean.csv"
REPORT_PATH = SCRIPT_DIR / "reconciliation_report.md"


# ---- Name normalization utilities ----

# Marketing suffixes and noise phrases commonly appended by the scraper
_NOISE_SUFFIXES = [
    r"\s*Course\s*Details?\s*\d{4}",          # "Course Details 2026"
    r"\s*Course\s*\d{4}",                      # "Course 2026"
    r"\s*\d{4}",                               # trailing year like "2026"
    r"\s*Colleges?\s+in\s+Chennai.*$",          # "Colleges in Chennai, India…"
    r"\s*(?:in|at)\s+SRM(?:IST)?.*$",           # "at SRMIST…" / "in SRM"
    r"\s*(?:Best|Top)\s+.*$",                   # "Best … Colleges …"
    r"\s*,\s*(?:Eligibility|Fees|Scope|Career|Admission|Curriculum).*$",
    r"\s*Pursue\s+Your\s+.*$",
    r"\s*Study\s+.*at\s+SRMIST\..*$",
    r"\s*Know\s+curriculum.*$",
]
_NOISE_RE_LIST = [re.compile(pat, re.IGNORECASE) for pat in _NOISE_SUFFIXES]

_WHITESPACE_RE = re.compile(r"\s+")
_SPECIAL_CHARS_RE = re.compile(r"[^\w\s.&/(),\-–—']")


def normalize_name(name: str) -> str:
    """Normalize a program name for comparison. Strips marketing noise."""
    n = name.strip()
    for r in _NOISE_RE_LIST:
        n = r.sub("", n).strip()
    # Normalize unicode dashes
    n = n.replace("\u2013", "-").replace("\u2014", "-")  # en-dash, em-dash
    n = n.replace("\xa0", " ").replace("\u200b", "")  # nbsp, zero-width
    n = _WHITESPACE_RE.sub(" ", n).strip()
    # Strip trailing periods that don't look like abbreviations
    if n.endswith(".") and not re.search(r"\b[A-Z]\.$", n):
        n = n.rstrip(".")
    return n


def normalize_for_comparison(name: str) -> str:
    """Lowercase + strip puncts for matching."""
    n = normalize_name(name).lower()
    n = n.replace("&", "and").replace("–", "-").replace("—", "-")
    n = re.sub(r"\bw/s\b", "with specialization", n)
    n = re.sub(r"\bhons\b\.?", "honours", n)
    n = re.sub(r"\bhonours\b", "honors", n)
    n = _WHITESPACE_RE.sub(" ", n).strip()
    return n


def tokenize(name: str) -> set[str]:
    """Tokenize for overlap matching."""
    STOP = {
        "and", "of", "the", "in", "with", "for", "at", "to", "a",
        "specialization", "specialisation", "course", "degree", "program",
        "programme", "best", "top", "colleges", "college", "chennai",
        "india", "srm", "srmist", "full", "time", "part", "honours",
        "honors", "hons",
    }
    n = normalize_for_comparison(name)
    n = re.sub(r"[^a-z0-9\s]", " ", n)
    return {t for t in n.split() if t and t not in STOP and len(t) > 1}


def url_slug(url: str) -> str:
    """Extract the last meaningful slug from a URL."""
    path = urlparse(url).path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    return parts[-1] if parts else ""


# ---- Matching engine ----

class MatchResult:
    """Result of matching a KG program to an official program."""
    def __init__(self, kg_id: str, kg_name: str, official_title: str,
                 official_url: str, score: float, method: str):
        self.kg_id = kg_id
        self.kg_name = kg_name
        self.official_title = official_title
        self.official_url = official_url
        self.score = score
        self.method = method


def match_programs(kg_data: dict, official_programs: list[dict]) -> dict:
    """
    Match KG programs against official CSV using multiple strategies.
    
    Returns dict with:
        matched: list[MatchResult]
        stale: list[dict]           (KG programs with no official match)
        missing: list[dict]         (official programs with no KG match)
    """
    kg_programs = {
        eid: e for eid, e in kg_data["entities"].items()
        if e["entity_type"] == "program"
    }



    # Build lookup indices
    kg_by_url_slug = {}
    kg_by_normalized = {}
    for eid, e in kg_programs.items():
        slug = url_slug(e.get("url", ""))
        if slug:
            kg_by_url_slug[slug] = eid
        norm = normalize_for_comparison(e["name"])
        kg_by_normalized[norm] = eid

    official_by_url_slug = {}
    for op in official_programs:
        slug = url_slug(op.get("URL", ""))
        if slug:
            official_by_url_slug[slug] = op

    matched: list[MatchResult] = []
    matched_kg_ids: set[str] = set()
    matched_official_titles: set[str] = set()

    # Strategy 1: URL slug match
    for op in official_programs:
        slug = url_slug(op.get("URL", ""))
        if slug and slug in kg_by_url_slug:
            eid = kg_by_url_slug[slug]
            if eid not in matched_kg_ids:
                matched.append(MatchResult(
                    kg_id=eid,
                    kg_name=kg_programs[eid]["name"],
                    official_title=op["Title"],
                    official_url=op.get("URL", ""),
                    score=1.0,
                    method="url_slug",
                ))
                matched_kg_ids.add(eid)
                matched_official_titles.add(op["Title"])

    # Strategy 2: Exact normalized name match
    for op in official_programs:
        if op["Title"] in matched_official_titles:
            continue
        norm = normalize_for_comparison(op["Title"])
        if norm in kg_by_normalized:
            eid = kg_by_normalized[norm]
            if eid not in matched_kg_ids:
                matched.append(MatchResult(
                    kg_id=eid,
                    kg_name=kg_programs[eid]["name"],
                    official_title=op["Title"],
                    official_url=op.get("URL", ""),
                    score=0.95,
                    method="normalized_name",
                ))
                matched_kg_ids.add(eid)
                matched_official_titles.add(op["Title"])

    # Strategy 3: Token overlap fuzzy match
    for op in official_programs:
        if op["Title"] in matched_official_titles:
            continue
        op_tokens = tokenize(op["Title"])
        if len(op_tokens) < 2:
            continue

        best_score = 0.0
        best_eid = None
        for eid, e in kg_programs.items():
            if eid in matched_kg_ids:
                continue
            kg_tokens = tokenize(e["name"])
            if not kg_tokens:
                continue

            intersection = op_tokens & kg_tokens
            union = op_tokens | kg_tokens
            jaccard = len(intersection) / len(union) if union else 0

            # Sequence similarity as tiebreaker
            seq_ratio = SequenceMatcher(
                None,
                normalize_for_comparison(op["Title"]),
                normalize_for_comparison(e["name"]),
            ).ratio()

            score = 0.5 * jaccard + 0.5 * seq_ratio
            if score > best_score:
                best_score = score
                best_eid = eid

        if best_eid and best_score >= 0.55:
            matched.append(MatchResult(
                kg_id=best_eid,
                kg_name=kg_programs[best_eid]["name"],
                official_title=op["Title"],
                official_url=op.get("URL", ""),
                score=round(best_score, 3),
                method="token_overlap",
            ))
            matched_kg_ids.add(best_eid)
            matched_official_titles.add(op["Title"])

    # Classify unmatched
    stale = [
        {"id": eid, **e}
        for eid, e in kg_programs.items()
        if eid not in matched_kg_ids
    ]
    missing = [
        op for op in official_programs
        if op["Title"] not in matched_official_titles
    ]

    return {"matched": matched, "stale": stale, "missing": missing}


# ---- Department fuzzy matching for missing programs ----

def find_best_department(kg_data: dict, program_title: str, program_url: str) -> Optional[str]:
    """
    Try to find the best department parent for a missing program by:
    1. URL slug heuristic (match /program/ slug against department names)
    2. Program name token overlap against department names
    """
    departments = {
        eid: e for eid, e in kg_data["entities"].items()
        if e["entity_type"] in ("department", "sub_college", "college", "school")
    }
    if not departments:
        return None

    prog_tokens = tokenize(program_title)

    best_score = 0.0
    best_dept = None

    for dept_id, dept in departments.items():
        dept_tokens = tokenize(dept["name"])
        if not dept_tokens:
            continue

        intersection = prog_tokens & dept_tokens
        if not intersection:
            continue

        # Jaccard similarity
        union = prog_tokens | dept_tokens
        score = len(intersection) / len(union) if union else 0

        if score > best_score:
            best_score = score
            best_dept = dept_id

    return best_dept if best_score >= 0.25 else None


# ---- Generate slug-based entity ID ----

def make_program_id(title: str) -> str:
    """Generate a program entity ID from title."""
    slug = title.lower().strip()
    slug = slug.replace("&", "and").replace("–", "-").replace("—", "-")
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return f"program--{slug}"


# ---- Apply logic ----

def apply_reconciliation(
    kg_data: dict,
    result: dict,
    official_programs: list[dict],
) -> dict:
    """Apply the reconciliation results to the knowledge graph data."""
    entities = kg_data["entities"]
    relationships = kg_data["relationships"]

    stats = {
        "renamed": 0,
        "urls_updated": 0,
        "stale_removed": 0,
        "missing_added": 0,
        "orphan_rels_removed": 0,
    }

    # 1. Rename matched programs to their official names and update URLs
    for m in result["matched"]:
        ent = entities.get(m.kg_id)
        if not ent:
            continue
        official_name = normalize_name(m.official_title)
        if ent["name"] != official_name:
            ent["name"] = official_name
            stats["renamed"] += 1
        if m.official_url and ent.get("url", "") != m.official_url:
            ent["url"] = m.official_url
            stats["urls_updated"] += 1

    # 2. Remove stale programs and their relationships
    stale_ids = {s["id"] for s in result["stale"]}
    # Keep stale programs that belong to non-KTR campuses as orphan nodes
    ktr_stale_ids = set()
    non_ktr_stale = []
    for s in result["stale"]:
        campus = s.get("campus", "KTR")
        if campus and campus != "KTR":
            non_ktr_stale.append(s)
        else:
            ktr_stale_ids.add(s["id"])

    # Remove KTR stale programs
    for sid in ktr_stale_ids:
        if sid in entities:
            del entities[sid]
            stats["stale_removed"] += 1

    # For non-KTR stale programs, remove all parents/links (keep as orphan nodes)
    for s in non_ktr_stale:
        relationships[:] = [
            r for r in relationships
            if not (r["target_id"] == s["id"] or r["source_id"] == s["id"])
        ]

    # Remove relationships pointing to/from removed entities
    valid_ids = set(entities.keys())
    before_rels = len(relationships)
    relationships[:] = [
        r for r in relationships
        if r["source_id"] in valid_ids and r["target_id"] in valid_ids
    ]
    stats["orphan_rels_removed"] = before_rels - len(relationships)

    # 3. Add missing programs
    # Build a lookup from the official list for extra metadata
    official_by_title = {op["Title"]: op for op in official_programs}

    for op in result["missing"]:
        title = op["Title"]
        clean_name = normalize_name(title)
        prog_id = make_program_id(clean_name)

        # Skip if ID already exists (unlikely but safe)
        if prog_id in entities:
            # Try appending a suffix
            prog_id = prog_id + "-new"
            if prog_id in entities:
                continue

        entities[prog_id] = {
            "id": prog_id,
            "name": clean_name,
            "entity_type": "program",
            "campus": "KTR",
            "url": op.get("URL", ""),
            "attributes": {
                "duration": op.get("Duration", ""),
                "annual_fees": op.get("Annual Fees", ""),
                "intake": op.get("Intake", ""),
                "source": "srm_program_finder",
            },
        }
        stats["missing_added"] += 1

        # Try to auto-assign to a department
        dept_id = find_best_department(kg_data, title, op.get("URL", ""))
        if dept_id:
            relationships.append({
                "source_id": dept_id,
                "target_id": prog_id,
                "relation_type": "offers_program",
                "metadata": {"auto_assigned": True},
            })

    return stats


# ---- Report generation ----

def generate_report(result: dict, stats: Optional[dict] = None) -> str:
    """Generate a markdown reconciliation report."""
    lines = [
        "# Program Reconciliation Report",
        "",
        f"**Generated by:** `reconcile_programs.py`",
        "",
        "## Summary",
        "",
        f"| Metric | Count |",
        f"|---|---|",
        f"| Programs matched (KG ↔ Official) | {len(result['matched'])} |",
        f"| Programs stale (KG only, not in official) | {len(result['stale'])} |",
        f"| Programs missing (official only, not in KG) | {len(result['missing'])} |",
    ]

    if stats:
        lines.extend([
            "",
            "## Applied Changes",
            "",
            f"| Action | Count |",
            f"|---|---|",
            f"| Programs renamed to official name | {stats['renamed']} |",
            f"| URLs updated | {stats['urls_updated']} |",
            f"| Stale programs removed | {stats['stale_removed']} |",
            f"| Missing programs added | {stats['missing_added']} |",
            f"| Orphan relationships removed | {stats['orphan_rels_removed']} |",
        ])

    lines.extend([
        "",
        "---",
        "",
        "## Matched Programs",
        "",
        "| KG Name | Official Name | Score | Method |",
        "|---|---|---|---|",
    ])
    for m in sorted(result["matched"], key=lambda x: x.score, reverse=True):
        name_changed = "✏️ " if normalize_name(m.kg_name) != normalize_name(m.official_title) else ""
        lines.append(
            f"| {name_changed}{m.kg_name} | {m.official_title} | {m.score:.2f} | {m.method} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## Stale Programs (in KG, not in official list)",
        "",
        "These programs exist in the KG but have no match in the official SRM Program Finder.",
        "",
        "| Name | ID | Campus | URL |",
        "|---|---|---|---|",
    ])
    for s in sorted(result["stale"], key=lambda x: x.get("name", "")):
        url = s.get("url", "") or ""
        url_display = f"[link]({url})" if url else "—"
        lines.append(f"| {s['name']} | `{s['id']}` | {s.get('campus', 'KTR')} | {url_display} |")

    lines.extend([
        "",
        "---",
        "",
        "## Missing Programs (in official list, not in KG)",
        "",
        "These programs are listed on the SRM Program Finder but missing from the KG.",
        "",
        "| Title | URL | Duration | Annual Fees |",
        "|---|---|---|---|",
    ])
    for op in sorted(result["missing"], key=lambda x: x.get("Title", "")):
        url = op.get("URL", "") or ""
        url_display = f"[link]({url})" if url else "—"
        lines.append(
            f"| {op['Title']} | {url_display} | {op.get('Duration', '')} | {op.get('Annual Fees', '')} |"
        )

    return "\n".join(lines) + "\n"


# ---- Save utilities ----

def save_kg(kg_data: dict) -> None:
    """Save knowledge_graph.json and regenerate knowledge_graph.js."""
    with open(KG_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(kg_data, f, indent=2, ensure_ascii=False)
    print(f"  [ok] Saved {KG_JSON_PATH}")

    js_content = "window.knowledgeGraphData = " + json.dumps(kg_data, indent=2, ensure_ascii=False) + ";\n"
    with open(KG_JS_PATH, "w", encoding="utf-8") as f:
        f.write(js_content)
    print(f"  [ok] Regenerated {KG_JS_PATH}")


# ---- Main ----

def main():
    parser = argparse.ArgumentParser(description="Reconcile KG programs with official SRM list")
    parser.add_argument("--apply", action="store_true", help="Apply fixes (rename, remove stale, add missing)")
    args = parser.parse_args()

    # Load data
    print("Loading knowledge graph...")
    with open(KG_JSON_PATH, "r", encoding="utf-8") as f:
        kg_data = json.load(f)

    print("Loading official program list...")
    official_programs = []
    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            official_programs.append(row)

    print(f"  KG programs: {sum(1 for e in kg_data['entities'].values() if e['entity_type'] == 'program')}")
    print(f"  Official programs: {len(official_programs)}")

    # Run matching
    print("\nRunning reconciliation...")
    result = match_programs(kg_data, official_programs)

    print(f"  Matched: {len(result['matched'])}")
    print(f"  Stale (KG only): {len(result['stale'])}")
    print(f"  Missing (official only): {len(result['missing'])}")

    # Count how many would be renamed
    rename_count = sum(
        1 for m in result["matched"]
        if normalize_name(m.kg_name) != normalize_name(m.official_title)
    )
    print(f"  Programs needing rename: {rename_count}")

    stats = None
    if args.apply:
        print("\n--- APPLYING FIXES ---")
        stats = apply_reconciliation(kg_data, result, official_programs)
        print(f"  Renamed: {stats['renamed']}")
        print(f"  URLs updated: {stats['urls_updated']}")
        print(f"  Stale removed: {stats['stale_removed']}")
        print(f"  Missing added: {stats['missing_added']}")
        print(f"  Orphan rels removed: {stats['orphan_rels_removed']}")

        save_kg(kg_data)
    else:
        print("\n  [info] Dry-run mode. Use --apply to apply fixes.")

    # Generate report
    report = generate_report(result, stats)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n  [report] Report saved to {REPORT_PATH}")


if __name__ == "__main__":
    main()
