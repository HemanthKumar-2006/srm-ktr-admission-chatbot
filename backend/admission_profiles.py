from __future__ import annotations

import csv
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

log = logging.getLogger("srm_chatbot.admissions")

ROUTE_ROOT_IDS = {
    "india": "admission--india",
    "international": "admission--international",
}

OFFICIAL_APPLICATION_HOSTS = {
    "applications.srmist.edu.in",
    "intlapplications.srmist.edu.in",
}

ADMISSION_CHILD_RE = re.compile(
    r"^https?://(?:www\.)?srmist\.edu\.in/admission-(india|international)/([^/?#]+)/?$",
    re.I,
)

ADMISSION_SECTION_SPECS: list[tuple[str, list[str]]] = [
    ("criteria", ["Admission Criteria"]),
    ("eligibility", ["Eligibility"]),
    ("how_to_apply", ["How to Apply"]),
    ("important_dates", ["Important Dates"]),
    ("exam_pattern_or_syllabus", ["Syllabus and Examination Pattern", "Syllabus", "Examination Pattern"]),
    ("scholarship", ["Scholarship"]),
    ("refund_policy", ["Refund Policy"]),
    ("faq_summary", ["FAQs", "FAQ"]),
]

ADMISSION_SCOPE_TARGETS: dict[str, list[str]] = {
    "engineering": ["college--faculty-of-engineering-and-technology"],
    "science-and-humanities": ["college--faculty-of-science-and-humanities"],
    "management": ["college--faculty-of-management"],
    "law": ["college--srm-school-of-law", "department--department-of-law"],
    "medicine-health-sciences": ["college--medicine-and-health-sciences"],
    "agricultural-science": ["college--college-of-agricultural-sciences"],
    "distance-education": ["directorate--directorate-of-distance-education"],
}

SECTION_FALLBACK_FIELDS = ("criteria", "eligibility", "how_to_apply", "important_dates")

_TEXT_NOISE_RE = re.compile(r"\s+")
_SECTION_NOISE_RE = re.compile(r"\bEdit Content\b", re.I)
_URL_RE = re.compile(r"https?://[^\s)>\]]+")
_CAMPUS_CODE_MAP = {
    "ktr": "KTR",
    "kattankulathur": "KTR",
    "rmp": "Ramapuram",
    "ramapuram": "Ramapuram",
    "vdp": "Vadapalani",
    "vadapalani": "Vadapalani",
    "ncr": "Delhi-NCR",
    "delhi-ncr": "Delhi-NCR",
    "delhi ncr": "Delhi-NCR",
    "hyn": "Delhi-NCR",
    "trichy": "Tiruchirappalli",
    "tiruchirappalli": "Tiruchirappalli",
    "amr": "Amaravati",
    "skm": "Sikkim",
    "bab": "Delhi-NCR",
}

_PROGRAM_STOPWORDS = {
    "and", "of", "the", "in", "with", "for", "specialization", "specialisation",
    "programme", "program", "programs", "degree", "full", "time", "part", "timings", "timing",
    "integrated", "hons", "honours", "honors", "regular", "stream", "course",
    "how", "apply", "application", "admission", "procedure", "process", "what",
    "when", "at", "to", "do", "i", "for", "the", "is",
}

_FIELD_KEYWORDS = {
    "fees": ("fee", "fees", "tuition", "cost"),
    "eligibility": ("eligibility", "eligible", "requirement", "requirements", "criteria"),
    "important_dates": ("date", "dates", "deadline", "deadlines", "schedule", "timeline", "last date"),
    "how_to_apply": ("apply", "application", "procedure", "process", "how to apply", "admission process"),
    "exam_pattern_or_syllabus": ("exam", "entrance", "srmjeee", "srmjeem", "syllabus", "pattern"),
    "scholarship": ("scholarship", "scholarships", "financial aid"),
    "refund_policy": ("refund", "withdrawal"),
    "faq_summary": ("faq", "faqs"),
}

_GENERIC_PROGRAM_TOKENS = {"btech", "mtech", "mba", "barch", "march", "bdes", "mdes", "llm", "phd"}


def save_admission_profiles(profiles: dict[str, dict], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2, ensure_ascii=False)


def load_admission_profiles(path: str | Path) -> dict[str, dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def integrate_admissions(kg: Any, pages: list[dict]) -> dict[str, dict]:
    profiles: dict[str, dict] = {}
    root_pages: dict[str, dict] = {}
    child_pages: list[tuple[str, str, dict]] = []
    portal_pages: dict[str, dict] = {}

    for page in pages:
        url = (page.get("meta", {}) or {}).get("url", "")
        if not url:
            continue
        host = urlparse(url).netloc.lower()
        if host in OFFICIAL_APPLICATION_HOSTS:
            portal_pages[_normalize_url(url)] = page
            continue

        child_match = ADMISSION_CHILD_RE.match(url)
        if child_match:
            child_pages.append((child_match.group(1).lower(), child_match.group(2).strip().lower(), page))
            continue

        normalized_url = url.lower().rstrip("/")
        if normalized_url == "https://www.srmist.edu.in/admission-india":
            root_pages["india"] = page
        elif normalized_url == "https://www.srmist.edu.in/admission-international":
            root_pages["international"] = page

    for route, admission_id in ROUTE_ROOT_IDS.items():
        if admission_id not in kg.entities:
            continue
        root_page = root_pages.get(route)
        if root_page:
            kg.entities[admission_id].url = root_page["meta"].get("url", "") or kg.entities[admission_id].url
        for campus_id in ("campus--kattankulathur", "campus--ramapuram", "campus--vadapalani"):
            if campus_id in kg.entities:
                kg.add_relationship(_rel(admission_id, campus_id, "admission_covers"))
        profiles[admission_id] = _build_profile(
            admission_id=admission_id,
            name=kg.entities[admission_id].name,
            route=route,
            scope="root",
            page=root_page,
            portal_pages=portal_pages,
        )
        kg.entities[admission_id].attributes.update({
            "route": route,
            "scope": "root",
            "source_url": profiles[admission_id]["source_url"],
            "apply_links": [link["url"] for link in profiles[admission_id]["apply_links"]],
        })

    for route, slug, page in child_pages:
        root_id = ROUTE_ROOT_IDS[route]
        admission_id = f"{root_id}--{slug}"
        title = ((page.get("meta", {}) or {}).get("title", "") or "").split("|")[0].strip()
        suffix = title or slug.replace("-", " ").title()
        name = f"{kg.entities[root_id].name} — {suffix}"

        if admission_id not in kg.entities:
            from backend.knowledge_graph import Entity

            kg.add_entity(Entity(
                id=admission_id,
                name=name,
                entity_type="admission",
                campus="KTR",
                url=page["meta"].get("url", ""),
                attributes={},
            ))
        else:
            kg.entities[admission_id].url = page["meta"].get("url", "")

        kg.entities[admission_id].attributes.update({
            "route": route,
            "scope": "faculty",
            "scope_slug": slug,
        })
        kg.add_relationship(_rel(root_id, admission_id, "has_admission_child"))

        for target_id in ADMISSION_SCOPE_TARGETS.get(slug, []):
            if target_id in kg.entities:
                kg.add_relationship(_rel(admission_id, target_id, "admission_covers"))

        profiles[admission_id] = _build_profile(
            admission_id=admission_id,
            name=name,
            route=route,
            scope="faculty",
            page=page,
            portal_pages=portal_pages,
        )
        kg.entities[admission_id].attributes.update({
            "source_url": profiles[admission_id]["source_url"],
            "apply_links": [link["url"] for link in profiles[admission_id]["apply_links"]],
        })

        for row in profiles[admission_id]["program_rows"]:
            match = _match_program_row(kg, row)
            if not match:
                continue
            row["program_id"] = match["program_id"]
            row["match_confidence"] = match["confidence"]
            row["match_method"] = match["method"]
            kg.add_relationship(_rel(
                admission_id,
                match["program_id"],
                "admission_governs",
                metadata={
                    "match_method": match["method"],
                    "match_confidence": match["confidence"],
                    "source_url": row["source_url"],
                },
            ))

    return profiles


def answer_admission_question(
    question: str,
    *,
    campus: str | None,
    kg: Any,
    profiles: dict[str, dict],
) -> Optional[dict[str, Any]]:
    if not kg or not profiles:
        return None

    q = (question or "").strip()
    if not q:
        return None
    q_low = q.lower()
    selected_campus = _detect_campus(q_low) or campus
    route = _detect_route(q_low)
    requested_fields = _detect_requested_fields(q_low)

    if "route" in q_low and "admission" in q_low and not _looks_program_specific(q_low):
        answer = _build_route_overview_answer(kg)
        if answer:
            return {
                "answer": answer,
                "sources": [
                    profiles["admission--india"]["source_url"],
                    profiles["admission--international"]["source_url"],
                ],
                "intent": "admission_query",
            }

    program_match = _match_program_text(kg, q_low) if _has_specific_program_hint(q_low) else None
    scope_matches = _match_admission_scope_entities(kg, q_low, route)

    if program_match:
        admission_ids = _find_program_admissions(kg, program_match["program_id"], route)
        if not admission_ids and scope_matches:
            admission_ids = [scope_matches[0].id]
        if not admission_ids:
            admission_ids = [ROUTE_ROOT_IDS[route]] if route else list(ROUTE_ROOT_IDS.values())

        sections = []
        sources: list[str] = []
        for admission_id in admission_ids:
            profile = profiles.get(admission_id)
            if not profile:
                continue
            section_text, section_sources = _build_program_answer(
                kg=kg,
                profile=profile,
                program_id=program_match["program_id"],
                requested_fields=requested_fields,
                campus=selected_campus,
                confidence=program_match["confidence"],
            )
            if section_text:
                sections.append(section_text)
                sources.extend(section_sources)

        if sections:
            return {
                "answer": "\n\n".join(sections),
                "sources": _unique(sources),
                "intent": "how_to_apply" if "how_to_apply" in requested_fields else "admission_query",
            }

    if scope_matches:
        sections = []
        sources: list[str] = []
        for ent in scope_matches:
            profile = profiles.get(ent.id)
            if not profile:
                continue
            text, section_sources = _build_scope_answer(profile, requested_fields)
            if text:
                sections.append(text)
                sources.extend(section_sources)
        if sections:
            return {
                "answer": "\n\n".join(sections),
                "sources": _unique(sources),
                "intent": "admission_query",
            }

    if any(term in q_low for term in ("admission", "apply", "application", "international", "india", "domestic")):
        answer = _build_root_answer(kg, profiles, route=route)
        if answer:
            source_ids = [ROUTE_ROOT_IDS[route]] if route else list(ROUTE_ROOT_IDS.values())
            return {
                "answer": answer,
                "sources": _unique([profiles[eid]["source_url"] for eid in source_ids if eid in profiles]),
                "intent": "admission_query",
            }

    return None


def _build_profile(
    *,
    admission_id: str,
    name: str,
    route: str,
    scope: str,
    page: Optional[dict],
    portal_pages: dict[str, dict],
) -> dict[str, Any]:
    base = {
        "admission_id": admission_id,
        "name": name,
        "route": route,
        "scope": scope,
        "source_url": "",
        "criteria": _empty_section(),
        "eligibility": _empty_section(),
        "fees": _empty_section(),
        "how_to_apply": _empty_section(),
        "important_dates": _empty_section(),
        "exam_pattern_or_syllabus": _empty_section(),
        "scholarship": _empty_section(),
        "refund_policy": _empty_section(),
        "faq_summary": _empty_section(),
        "apply_links": [],
        "exam_links": [],
        "prospectus_links": [],
        "program_rows": [],
    }
    if not page:
        return base

    meta = page.get("meta", {}) or {}
    source_url = meta.get("url", "")
    scraped_at = meta.get("scraped_at", "")
    content = page.get("content", "") or ""
    sections = _extract_sections(content)
    raw_links = _extract_raw_links(page.get("folder"))
    enriched_links = _enrich_with_portal_pages(raw_links, portal_pages)

    base["source_url"] = source_url
    for field, _aliases in ADMISSION_SECTION_SPECS:
        text = sections.get(field, "")
        if field == "fees" and not text:
            text = _fees_summary_from_tables(page.get("folder"))
        if text:
            base[field] = {
                "text": _clean_text(text),
                "source_url": source_url,
                "last_scraped_at": scraped_at,
                "source_type": "main_site",
            }

    base["apply_links"] = _categorize_links(enriched_links, "apply", source_url, scraped_at)
    base["exam_links"] = _categorize_links(enriched_links, "exam", source_url, scraped_at)
    base["prospectus_links"] = _categorize_links(enriched_links, "prospectus", source_url, scraped_at)
    base["program_rows"] = _extract_program_rows(
        folder=page.get("folder"),
        apply_links=base["apply_links"],
        route=route,
        source_url=source_url,
        scraped_at=scraped_at,
        criteria_text=base["criteria"]["text"],
        how_to_apply_text=base["how_to_apply"]["text"],
    )
    return base


def _extract_sections(content: str) -> dict[str, str]:
    normalized = _clean_text(content)
    if not normalized:
        return {}

    matches: list[tuple[int, str, str]] = []
    for field, aliases in ADMISSION_SECTION_SPECS:
        for alias in aliases:
            match = re.search(rf"\b{re.escape(alias)}\b", normalized, re.I)
            if match:
                matches.append((match.start(), field, alias))
                break
    if not matches:
        return {}

    matches.sort(key=lambda item: item[0])
    sections: dict[str, str] = {}
    for idx, (start, field, alias) in enumerate(matches):
        end = matches[idx + 1][0] if idx + 1 < len(matches) else len(normalized)
        block = normalized[start:end]
        block = re.sub(rf"^{re.escape(alias)}\s*", "", block, flags=re.I)
        block = _SECTION_NOISE_RE.sub(" ", block)
        block = _clean_text(block)
        if block:
            sections[field] = block
    return sections


def _extract_raw_links(folder: Optional[Path]) -> list[dict[str, str]]:
    if not folder:
        return []
    raw_html = Path(folder) / "raw.html"
    if not raw_html.exists():
        return []

    try:
        soup = BeautifulSoup(raw_html.read_text(encoding="utf-8"), "html.parser")
    except Exception as exc:
        log.debug("Could not parse raw HTML for %s: %s", folder, exc)
        return []

    links = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        label = _clean_text(anchor.get_text(" ", strip=True))
        if not href or not label:
            continue
        if href.startswith("//"):
            href = f"https:{href}"
        elif href.startswith("/"):
            href = f"https://www.srmist.edu.in{href}"
        links.append({"label": label, "url": href})

    text = soup.get_text(" ", strip=True)
    for url in _URL_RE.findall(text):
        links.append({"label": url, "url": url})
    return _unique_link_dicts(links)


def _enrich_with_portal_pages(links: list[dict[str, str]], portal_pages: dict[str, dict]) -> list[dict[str, str]]:
    enriched = []
    for link in links:
        normalized_url = _normalize_url(link["url"])
        portal_page = portal_pages.get(normalized_url)
        item = dict(link)
        if portal_page:
            item["portal_title"] = ((portal_page.get("meta", {}) or {}).get("title", "") or "").strip()
        enriched.append(item)
    return enriched


def _categorize_links(
    links: list[dict[str, str]],
    category: str,
    source_url: str,
    scraped_at: str,
) -> list[dict[str, str]]:
    results = []
    for link in links:
        label_low = link.get("label", "").lower()
        host = urlparse(link["url"]).netloc.lower()
        url_low = link["url"].lower()
        is_apply = (
            host in OFFICIAL_APPLICATION_HOSTS
            or "apply now" in label_low
            or "application form" in label_low
            or ("apply" in label_low and "hostel" not in url_low)
        )
        is_exam = any(term in label_low for term in ("instruction manual", "syllabus", "examination pattern", "question paper", "exam"))
        is_prospectus = "prospectus" in label_low

        should_keep = (
            (category == "apply" and is_apply)
            or (category == "exam" and is_exam)
            or (category == "prospectus" and is_prospectus)
        )
        if not should_keep:
            continue

        results.append({
            "label": link["label"],
            "url": link["url"],
            "source_url": source_url,
            "last_scraped_at": scraped_at,
            "source_type": "application_portal" if host in OFFICIAL_APPLICATION_HOSTS else "main_site",
        })
    deduped = _unique_link_dicts(results)
    return sorted(
        deduped,
        key=lambda item: (
            0 if urlparse(item["url"]).netloc.lower() in OFFICIAL_APPLICATION_HOSTS else 1,
            0 if "application form" in item["label"].lower() or "apply now" in item["label"].lower() else 1,
            item["label"].lower(),
        ),
    )


def _extract_program_rows(
    *,
    folder: Optional[Path],
    apply_links: list[dict[str, str]],
    route: str,
    source_url: str,
    scraped_at: str,
    criteria_text: str,
    how_to_apply_text: str,
) -> list[dict[str, Any]]:
    if not folder:
        return []

    tables_dir = Path(folder) / "tables"
    if not tables_dir.exists():
        return []

    rows: list[dict[str, Any]] = []
    for csv_path in sorted(tables_dir.glob("table_*.csv")):
        try:
            with open(csv_path, encoding="utf-8") as f:
                parsed_rows = list(csv.reader(f))
        except Exception as exc:
            log.debug("Could not read %s: %s", csv_path, exc)
            continue
        if not parsed_rows:
            continue

        header = [_clean_text(value) for value in parsed_rows[0]]
        header_low = [value.lower() for value in header]
        if not ({"campus", "degree"} <= set(header_low) and any("fees" in item for item in header_low)):
            continue

        for raw in parsed_rows[1:]:
            row = {header[idx]: raw[idx] if idx < len(raw) else "" for idx in range(len(header))}
            degree_value = row.get(_find_header(header, "Degree"), "")
            specialization_value = row.get(_find_header(header, "Branch With Specialization"), "") or row.get(_find_header(header, "Program"), "")
            if not degree_value or not specialization_value:
                continue

            degree = _clean_degree(degree_value)
            specialization = _clean_specialization(specialization_value)
            rows.append({
                "campus": _normalize_campus(row.get(_find_header(header, "Campus"), "")),
                "degree": degree,
                "specialization": specialization,
                "intake": _clean_text(row.get(_find_header(header, "Intake"), "")),
                "duration": _clean_text(row.get(_find_header(header, "Duration (Years)"), "")),
                "annual_fees": _clean_text(row.get(_find_header(header, "Annual Fees"), "")),
                "dept": _clean_text(row.get(_find_header(header, "Dept"), "")),
                "program_level": _clean_text(row.get(_find_header(header, "Program Level"), "")),
                "program_type": _clean_text(row.get(_find_header(header, "Program Type"), "")),
                "eligibility_override": _clean_text(row.get(_find_header(header, "Eligibility"), "")),
                "apply_url": _infer_apply_url(apply_links, degree, specialization, route=route),
                "exam": _infer_exam_name(degree, specialization, criteria_text, how_to_apply_text),
                "source_url": source_url,
                "last_scraped_at": scraped_at,
                "source_type": "main_site",
                "match_confidence": 0.0,
                "match_method": "",
                "program_id": "",
            })
    return rows


def _match_program_row(kg: Any, row: dict[str, Any]) -> Optional[dict[str, Any]]:
    query_text = _build_program_query_text(row["degree"], row["specialization"])
    query_tokens = _program_tokens(query_text)
    if not query_tokens:
        return None

    best: Optional[dict[str, Any]] = None
    for entity_id, entity in kg.entities.items():
        if getattr(entity, "entity_type", "") != "program":
            continue
        candidate_tokens = _program_tokens(f"{entity.name} {entity.url}")
        if not candidate_tokens:
            continue

        overlap = len(query_tokens & candidate_tokens) / max(len(query_tokens), 1)
        contains_bonus = 0.2 if _normalize_program_text(query_text) in _normalize_program_text(entity.name) else 0.0
        degree_bonus = 0.1 if _normalize_program_text(row["degree"]) in _normalize_program_text(entity.name) else 0.0
        dept_bonus = 0.0
        parent_name = _get_program_parent_name(kg, entity_id)
        if row.get("dept") and parent_name and _token_overlap(_program_tokens(row["dept"]), _program_tokens(parent_name)) >= 0.4:
            dept_bonus = 0.15

        score = overlap + contains_bonus + degree_bonus + dept_bonus
        if score < 0.45:
            continue
        method = "token_overlap"
        if contains_bonus:
            method = "normalized_contains"
        if dept_bonus:
            method = "token_overlap+dept_validation"

        if not best or score > best["confidence"]:
            best = {
                "program_id": entity_id,
                "confidence": round(min(score, 0.99), 3),
                "method": method,
            }
    return best


def _match_program_text(kg: Any, question: str) -> Optional[dict[str, Any]]:
    normalized_question = _normalize_program_text(question)
    best_exact = None
    for entity_id, entity in kg.entities.items():
        if getattr(entity, "entity_type", "") != "program":
            continue
        normalized_name = _normalize_program_text(entity.name)
        if normalized_name and (normalized_name in normalized_question or normalized_question in normalized_name):
            if not best_exact or len(normalized_name) > len(best_exact["matched_name"]):
                best_exact = {
                    "program_id": entity_id,
                    "confidence": 0.99,
                    "method": "normalized_name_substring",
                    "matched_name": normalized_name,
                }
    if best_exact:
        return best_exact

    query_tokens = _program_tokens(question)
    best = None
    for entity_id, entity in kg.entities.items():
        if getattr(entity, "entity_type", "") != "program":
            continue
        overlap = _token_overlap(query_tokens, _program_tokens(entity.name))
        if overlap < 0.45:
            continue
        score = overlap
        if any(token in entity.name.lower() for token in ("b.tech", "m.tech", "mba", "llm")):
            score += 0.05
        if not best or score > best["confidence"]:
            best = {
                "program_id": entity_id,
                "confidence": round(min(score, 0.95), 3),
                "method": "question_token_overlap",
            }
    return best


def _match_admission_scope_entities(kg: Any, question: str, route: Optional[str]) -> list[Any]:
    matches = []
    for entity in kg.entities.values():
        if getattr(entity, "entity_type", "") != "admission":
            continue
        attrs = getattr(entity, "attributes", {}) or {}
        if attrs.get("scope") != "faculty":
            continue
        if route and attrs.get("route") != route:
            continue
        scope_slug = attrs.get("scope_slug", "")
        candidate_texts = [entity.name.lower(), scope_slug.replace("-", " ")]
        if any(text and text in question for text in candidate_texts):
            matches.append(entity)
    return matches


def _find_program_admissions(kg: Any, program_id: str, route: Optional[str]) -> list[str]:
    admission_ids = []
    for rel in kg.relationships:
        if rel.relation_type != "admission_governs" or rel.target_id != program_id:
            continue
        source = kg.entities.get(rel.source_id)
        if not source:
            continue
        attrs = source.attributes or {}
        if route and attrs.get("route") != route:
            continue
        admission_ids.append(rel.source_id)
    if not admission_ids:
        lineage_ids = _get_program_lineage_ids(kg, program_id)
        for rel in kg.relationships:
            if rel.relation_type != "admission_covers" or rel.target_id not in lineage_ids:
                continue
            source = kg.entities.get(rel.source_id)
            if not source:
                continue
            attrs = source.attributes or {}
            if route and attrs.get("route") != route:
                continue
            admission_ids.append(rel.source_id)
    if not admission_ids and route:
        root_id = ROUTE_ROOT_IDS[route]
        if root_id in kg.entities:
            admission_ids.append(root_id)
    elif not admission_ids:
        admission_ids.extend([eid for eid in ROUTE_ROOT_IDS.values() if eid in kg.entities])
    unique_ids = _unique(admission_ids)
    specific_ids = [
        admission_id
        for admission_id in unique_ids
        if (kg.entities.get(admission_id).attributes or {}).get("scope") == "faculty"
    ]
    return specific_ids or unique_ids


def _build_program_answer(
    *,
    kg: Any,
    profile: dict[str, Any],
    program_id: str,
    requested_fields: set[str],
    campus: str | None,
    confidence: float,
) -> tuple[str, list[str]]:
    program = kg.entities.get(program_id)
    if not program:
        return "", []

    row = _find_best_row(profile.get("program_rows", []), program_id, campus)
    lines = [f"{profile['name']} for {program.name}:"]
    sources = [profile["source_url"]]
    fields = requested_fields or {"how_to_apply", "eligibility", "important_dates", "fees"}

    if confidence < 0.6:
        lines.append("Program-level mapping is not fully confirmed, so I am using the closest matching admissions page.")

    if "how_to_apply" in fields:
        apply_bits = []
        exam = row.get("exam") if row else ""
        if exam:
            apply_bits.append(f"Route / exam: {exam}.")
        apply_url = row.get("apply_url") if row else ""
        if not apply_url:
            apply_url = _infer_apply_url(
                profile.get("apply_links", []),
                program.name,
                program.name,
                route=profile.get("route"),
            )
        if apply_url:
            apply_bits.append(f"Apply here: {apply_url}")
            sources.append(apply_url)
        how_to_apply = profile.get("how_to_apply", {}).get("text", "")
        if how_to_apply:
            apply_bits.append(_excerpt(how_to_apply))
        if apply_bits:
            lines.append("How to apply: " + " ".join(apply_bits))

    if "eligibility" in fields:
        eligibility = ""
        if row and row.get("eligibility_override"):
            eligibility = row["eligibility_override"]
        elif profile.get("eligibility", {}).get("text"):
            eligibility = profile["eligibility"]["text"]
        elif profile.get("criteria", {}).get("text"):
            eligibility = profile["criteria"]["text"]
        if eligibility:
            lines.append("Eligibility: " + _excerpt(eligibility))

    if "fees" in fields:
        fees_bits = []
        if row and row.get("annual_fees"):
            campus_prefix = f"{row['campus']} " if row.get("campus") else ""
            fees_bits.append(f"{campus_prefix}annual fee: {row['annual_fees']}.")
        elif profile.get("fees", {}).get("text"):
            fees_bits.append(_excerpt(profile["fees"]["text"]))
        if fees_bits:
            lines.append("Fees: " + " ".join(fees_bits))

    if "important_dates" in fields and profile.get("important_dates", {}).get("text"):
        lines.append("Important dates: " + _excerpt(profile["important_dates"]["text"]))

    if "exam_pattern_or_syllabus" in fields and profile.get("exam_pattern_or_syllabus", {}).get("text"):
        lines.append("Exam / syllabus: " + _excerpt(profile["exam_pattern_or_syllabus"]["text"]))

    if "scholarship" in fields and profile.get("scholarship", {}).get("text"):
        lines.append("Scholarship: " + _excerpt(profile["scholarship"]["text"]))

    if "refund_policy" in fields and profile.get("refund_policy", {}).get("text"):
        lines.append("Refund policy: " + _excerpt(profile["refund_policy"]["text"]))

    if row and row.get("campus"):
        lines.append(f"Matched campus context: {row['campus']}.")

    return "\n".join(lines), _unique(sources)


def _build_scope_answer(profile: dict[str, Any], requested_fields: set[str]) -> tuple[str, list[str]]:
    lines = [f"{profile['name']}:"]
    sources = [profile["source_url"]]
    fields = requested_fields or {"criteria", "eligibility", "how_to_apply", "important_dates"}

    for field in ("criteria", "eligibility", "how_to_apply", "important_dates", "exam_pattern_or_syllabus", "scholarship", "refund_policy", "faq_summary"):
        if field not in fields:
            continue
        text = profile.get(field, {}).get("text", "")
        if text:
            lines.append(f"{field.replace('_', ' ').title()}: {_excerpt(text)}")

    first_apply = _pick_first_link(profile.get("apply_links", []))
    if first_apply and "how_to_apply" in fields:
        lines.append(f"Apply link: {first_apply}")
        sources.append(first_apply)

    return "\n".join(lines), _unique(sources)


def _build_root_answer(kg: Any, profiles: dict[str, dict], route: Optional[str]) -> Optional[str]:
    route_ids = [ROUTE_ROOT_IDS[route]] if route else list(ROUTE_ROOT_IDS.values())
    lines = []
    for root_id in route_ids:
        entity = kg.entities.get(root_id)
        if not entity:
            continue
        lines.append(f"{entity.name}: {entity.url}")
        children = [
            kg.entities[rel.target_id].name
            for rel in kg.relationships
            if rel.source_id == root_id and rel.relation_type == "has_admission_child" and rel.target_id in kg.entities
        ]
        if children:
            lines.append("Includes: " + ", ".join(sorted(children)))
        preferred_host = "intlapplications.srmist.edu.in" if root_id == "admission--international" else None
        first_apply = _pick_first_link((profiles.get(root_id) or {}).get("apply_links", []), preferred_host=preferred_host)
        if first_apply:
            lines.append(f"Primary apply link: {first_apply}")
    return "\n".join(lines) if lines else None


def _build_route_overview_answer(kg: Any) -> Optional[str]:
    india = kg.entities.get("admission--india")
    international = kg.entities.get("admission--international")
    if not india or not international:
        return None
    return "\n".join([
        "SRMIST has two main admission routes:",
        f"- {india.name}: {india.url}",
        f"- {international.name}: {international.url}",
    ])


def _find_best_row(rows: list[dict[str, Any]], program_id: str, campus: str | None) -> Optional[dict[str, Any]]:
    exact_rows = [row for row in rows if row.get("program_id") == program_id]
    if not exact_rows:
        return None
    if campus:
        normalized_campus = _normalize_campus(campus)
        for row in exact_rows:
            if row.get("campus") == normalized_campus:
                return row
    return sorted(exact_rows, key=lambda item: item.get("match_confidence", 0), reverse=True)[0]


def _infer_apply_url(
    links: list[dict[str, str]],
    degree: str,
    specialization: str,
    *,
    route: str | None = None,
) -> str:
    degree_low = degree.lower()
    specialization_low = specialization.lower()
    if route == "international":
        for link in links:
            if urlparse(link["url"]).netloc.lower() == "intlapplications.srmist.edu.in":
                return link["url"]
    for link in links:
        label_low = link["label"].lower()
        url_low = link["url"].lower()
        if ("b.tech" in degree_low or "btech" in degree_low) and ("b.tech" in label_low or "/btech" in url_low):
            return link["url"]
        if ("m.tech" in degree_low or "mtech" in degree_low) and ("m.tech" in label_low or "/m-tech" in url_low):
            return link["url"]
        if ("b.arch" in degree_low or "b.des" in degree_low) and ("arch" in url_low or "design" in url_low):
            return link["url"]
        if ("m.arch" in degree_low or "m.des" in degree_low) and ("m-arch" in url_low or "m-des" in url_low):
            return link["url"]
        if any(term in specialization_low for term in ("mba", "bba")) and any(term in url_low for term in ("management", "mba", "bba")):
            return link["url"]
    return _pick_first_link(links)


def _infer_exam_name(degree: str, specialization: str, criteria_text: str, how_to_apply_text: str) -> str:
    joined = f"{degree} {specialization} {criteria_text} {how_to_apply_text}".lower()
    if "srmjeee (ug)" in joined or "srmjeee ug" in joined or "b.tech" in degree.lower() or "btech" in degree.lower():
        return "SRMJEEE (UG)"
    if "srmjeee (pg)" in joined or "srmjeee pg" in joined or "m.tech" in degree.lower() or "mtech" in degree.lower():
        return "SRMJEEE (PG)"
    if "nata" in joined:
        return "NATA"
    if "ceed" in joined:
        return "CEED"
    if "uceed" in joined:
        return "UCEED"
    if "srmjeem" in joined or "mba" in degree.lower():
        return "SRMJEEM"
    return ""


def _fees_summary_from_tables(folder: Optional[Path]) -> str:
    if not folder:
        return ""
    tables_dir = Path(folder) / "tables"
    if not tables_dir.exists():
        return ""
    for csv_path in sorted(tables_dir.glob("table_*.csv")):
        try:
            lines = csv_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        if any("Annual Fees" in line for line in lines[:3]):
            return _clean_text(" ".join(lines[:12]))
    return ""


def _empty_section() -> dict[str, str]:
    return {
        "text": "",
        "source_url": "",
        "last_scraped_at": "",
        "source_type": "",
    }


def _rel(source_id: str, target_id: str, relation_type: str, metadata: Optional[dict[str, Any]] = None) -> Any:
    from backend.knowledge_graph import Relationship

    return Relationship(source_id=source_id, target_id=target_id, relation_type=relation_type, metadata=metadata or {})


def _find_header(header: list[str], expected: str) -> str:
    expected_low = expected.lower()
    for item in header:
        if item.lower() == expected_low:
            return item
    return expected


def _detect_route(question: str) -> Optional[str]:
    if "international" in question or "nri" in question or "foreign" in question:
        return "international"
    if "india" in question or "domestic" in question or "resident indian" in question:
        return "india"
    return None


def _detect_requested_fields(question: str) -> set[str]:
    fields = {
        field
        for field, keywords in _FIELD_KEYWORDS.items()
        if any(keyword in question for keyword in keywords)
    }
    if not fields and any(term in question for term in ("admission", "apply", "application", "procedure", "process")):
        fields.update({"how_to_apply", "eligibility", "important_dates"})
    return fields


def _detect_campus(question: str) -> Optional[str]:
    for alias, campus in _CAMPUS_CODE_MAP.items():
        if alias in question:
            return campus
    return None


def _looks_program_specific(question: str) -> bool:
    return any(token in question for token in ("b.tech", "btech", "m.tech", "mtech", "mba", "llm", "program"))


def _has_specific_program_hint(question: str) -> bool:
    tokens = _program_tokens(question) - _GENERIC_PROGRAM_TOKENS
    return len(tokens) >= 2


def _normalize_campus(value: str) -> str:
    cleaned = _clean_text(value).lower()
    return _CAMPUS_CODE_MAP.get(cleaned, _clean_text(value))


def _clean_degree(value: str) -> str:
    cleaned = _clean_text(value)
    cleaned = re.sub(r"\bB\.\s*Tech\b", "B.Tech", cleaned, flags=re.I)
    cleaned = re.sub(r"\bM\.\s*Tech\b", "M.Tech", cleaned, flags=re.I)
    return cleaned


def _clean_specialization(value: str) -> str:
    return _clean_text(
        value.replace("W/S", "with specialization in").replace("w/s", "with specialization in")
    )


def _build_program_query_text(degree: str, specialization: str) -> str:
    return _clean_text(f"{degree} {specialization}")


def _normalize_program_text(text: str) -> str:
    value = text.lower()
    replacements = {
        r"\bb\.?\s*tech\b": "btech",
        r"\bm\.?\s*tech\b": "mtech",
        r"\bb\.?\s*arch\b": "barch",
        r"\bm\.?\s*arch\b": "march",
        r"\bb\.?\s*des\b": "bdes",
        r"\bm\.?\s*des\b": "mdes",
        r"\bm\.?\s*b\.?\s*a\b": "mba",
        r"\bw/?s\b": "with specialization",
        r"&": " and ",
    }
    for pattern, replacement in replacements.items():
        value = re.sub(pattern, replacement, value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return _clean_text(value)


def _program_tokens(text: str) -> set[str]:
    normalized = _normalize_program_text(text)
    return {
        token for token in normalized.split()
        if token and token not in _PROGRAM_STOPWORDS and len(token) > 1
    }


def _token_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), 1)


def _get_program_parent_name(kg: Any, program_id: str) -> str:
    for rel in kg.relationships:
        if rel.relation_type == "offers_program" and rel.target_id == program_id:
            parent = kg.entities.get(rel.source_id)
            if parent:
                return parent.name
    return ""


def _get_program_lineage_ids(kg: Any, program_id: str) -> set[str]:
    lineage: set[str] = set()
    frontier = {program_id}
    visited = set()
    while frontier:
        current = frontier.pop()
        if current in visited:
            continue
        visited.add(current)
        for rel in kg.relationships:
            if rel.target_id != current:
                continue
            if rel.relation_type not in {"offers_program", "has_department", "has_sub_college", "has_college", "has_campus"}:
                continue
            lineage.add(rel.source_id)
            frontier.add(rel.source_id)
    return lineage


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(query="", fragment="").geturl().rstrip("/").lower()


def _pick_first_link(links: list[dict[str, str]], preferred_host: str | None = None) -> str:
    if not links:
        return ""
    if preferred_host:
        for link in links:
            if urlparse(link["url"]).netloc.lower() == preferred_host:
                return link["url"]
    for link in links:
        if urlparse(link["url"]).netloc.lower() in OFFICIAL_APPLICATION_HOSTS:
            return link["url"]
    return links[0]["url"]


def _clean_text(text: Any) -> str:
    cleaned = _SECTION_NOISE_RE.sub(" ", str(text or ""))
    return _TEXT_NOISE_RE.sub(" ", cleaned).strip()


def _excerpt(text: str, max_len: int = 320) -> str:
    text = _clean_text(text)
    if len(text) <= max_len:
        return text
    snippet = text[:max_len].rsplit(" ", 1)[0].strip()
    return snippet + "..."


def _unique(items: list[Any]) -> list[Any]:
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _unique_link_dicts(links: list[dict[str, str]]) -> list[dict[str, str]]:
    seen = set()
    result = []
    for link in links:
        key = (link.get("label", ""), link.get("url", ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(link)
    return result
