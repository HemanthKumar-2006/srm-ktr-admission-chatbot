from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

from backend.admission_profiles import (
    _has_specific_program_hint,
    _match_program_text,
    _normalize_program_text,
)

_ALLOWED_DOMAINS = {
    "admissions",
    "programs",
    "departments",
    "faculty",
    "fees",
    "campus_life",
    "placements",
    "research",
    "general",
}
_ALLOWED_TASKS = {
    "lookup",
    "list",
    "compare",
    "eligibility_check",
    "procedure",
    "timeline",
    "general",
}
_ALLOWED_TARGETS = {
    "admissions",
    "kg_listing",
    "kg_role",
    "comparison",
    "retrieval",
}

_COMPARE_RE = re.compile(r"\b(compare|comparison|vs\.?|versus|difference between|better)\b", re.I)
_LIST_RE = re.compile(
    r"\b("
    r"list|what are|which|how many|all|available|"
    r"what\s+(?:departments|programs|courses)|"
    r"programs?\s+(?:are\s+)?offered|"
    r"courses?\s+(?:are\s+)?available|"
    r"departments?\s+(?:are\s+)?under"
    r")\b",
    re.I,
)
_ELIGIBILITY_RE = re.compile(r"\b(eligible|eligibility|criteria|requirements?|who can apply)\b", re.I)
_PROCEDURE_RE = re.compile(r"\b(how to|how do i|steps|process|procedure|apply)\b", re.I)
_TIMELINE_RE = re.compile(r"\b(date|dates|deadline|deadlines|schedule|timeline|when|last date|opening)\b", re.I)
_ROLE_RE = re.compile(r"\b(hod|head of|head of department|chairperson|dean|principal|director|registrar)\b", re.I)
_FEES_RE = re.compile(r"\b(fee|fees|tuition|cost)\b", re.I)
_ADMISSION_RE = re.compile(r"\b(admission|admissions|apply|application|srmjeee|entrance|scholarship|counselling|seat)\b", re.I)
_PLACEMENT_RE = re.compile(r"\b(placement|placements|recruitment|companies|package|salary|internship)\b", re.I)
_RESEARCH_RE = re.compile(r"\b(research|publication|lab|centre of excellence|funding|patent)\b", re.I)
_CAMPUS_LIFE_RE = re.compile(r"\b(hostel|campus life|clubs|fest|events|sports|accommodation|transport|library)\b", re.I)
_PROGRAM_COMPARE_SPLIT_RE = re.compile(r"\b(?:vs\.?|versus|and)\b", re.I)
_PERSON_NAME_RE = re.compile(r"\b(?:dr|prof)\.?\s+([A-Z][A-Za-z.\-' ]+)", re.I)
_DEPARTMENT_TERM_RE = re.compile(r"\b(department|departments)\b", re.I)
_PROGRAM_TERM_RE = re.compile(r"\b(program|programs|course|courses)\b", re.I)

_PROGRAM_DEGREE_TOKENS = {"btech", "mtech", "mba", "barch", "march", "bdes", "mdes", "llm", "phd"}
_MATCH_STOPWORDS = {
    "and", "of", "the", "for", "in", "at",
    "how", "what", "who", "when", "which", "where",
    "do", "does", "i", "can", "you", "tell", "me", "about",
}
_MATCH_ALIAS_REPLACEMENTS = (
    (r"\bai\s*(?:&|/)\s*ml\b", "aiml"),
    (r"\bai\s+and\s+ml\b", "aiml"),
    (r"\baiml\b", "artificial intelligence machine learning"),
    (r"\bcse\b", "computer science engineering"),
    (r"\bece\b", "electronics communication engineering"),
    (r"\beee\b", "electrical electronics engineering"),
    (r"\bmech\b", "mechanical engineering"),
    (r"\bcivil\b", "civil engineering"),
    (r"\bcsbs\b", "computer science business systems"),
    (r"&", " and "),
)
_CAMPUS_ALIASES = {
    "ktr": "KTR",
    "kattankulathur": "KTR",
    "ramapuram": "Ramapuram",
    "rmp": "Ramapuram",
    "vadapalani": "Vadapalani",
    "vdp": "Vadapalani",
    "ghaziabad": "Delhi-NCR",
    "delhi ncr": "Delhi-NCR",
    "delhi-ncr": "Delhi-NCR",
    "ncr": "Delhi-NCR",
    "tiruchirappalli": "Tiruchirappalli",
    "trichy": "Tiruchirappalli",
}


@dataclass
class RouteDecision:
    domain: str = "general"
    task: str = "general"
    routing_target: str = "retrieval"
    confidence: float = 0.0
    needs_decomposition: bool = False
    used_llm_fallback: bool = False
    used_pinned_context: bool = False
    entities: dict[str, Any] = field(default_factory=dict)
    entity_ids: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_metadata(self, freshness: str | None = None) -> dict[str, Any]:
        metadata = {
            "domain": self.domain,
            "task": self.task,
            "routing_target": self.routing_target,
            "confidence": round(self.confidence, 3) if self.confidence else None,
            "entities": {k: v for k, v in self.entities.items() if v},
            "freshness": freshness,
            "used_pinned_context": self.used_pinned_context,
            "decomposed": self.needs_decomposition,
        }
        return metadata

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _extract_json_object(text: str) -> dict[str, Any]:
    if not text:
        return {}
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def _normalize_campus(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = str(value).strip().lower()
    return _CAMPUS_ALIASES.get(cleaned, value.strip())


def _extract_campus(text: str) -> str | None:
    lowered = text.lower()
    for alias, campus in sorted(_CAMPUS_ALIASES.items(), key=lambda item: -len(item[0])):
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return campus
    return None


def _normalize_match_text(text: str) -> str:
    value = text.lower()
    for pattern, replacement in _MATCH_ALIAS_REPLACEMENTS:
        value = re.sub(pattern, replacement, value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    tokens = [token for token in value.split() if token and token not in _MATCH_STOPWORDS]
    return " ".join(tokens)


def _find_longest_entity(text: str, kg: Any, entity_types: set[str]) -> tuple[str | None, str | None]:
    if not kg:
        return None, None

    normalized_text = _normalize_match_text(text)
    best_id = None
    best_name = None
    best_len = 0
    for entity in kg.entities.values():
        if entity.entity_type not in entity_types:
            continue
        normalized_name = _normalize_match_text(entity.name)
        candidate_names = [normalized_name]
        stripped_name = re.sub(
            r"^(department|faculty|college|school|directorate|centre|center|division)\s+",
            "",
            normalized_name,
        )
        if stripped_name and stripped_name != normalized_name:
            candidate_names.append(stripped_name)
        matched_name = next((name for name in candidate_names if name and name in normalized_text), None)
        if matched_name and len(matched_name) > best_len:
            best_id = entity.id
            best_name = entity.name
            best_len = len(matched_name)
    return best_id, best_name


def _extract_person_name(text: str) -> str | None:
    match = _PERSON_NAME_RE.search(text)
    if not match:
        return None
    return match.group(1).strip()


def _prepare_compare_text(text: str) -> str:
    return re.sub(r"\bai\s*(?:&|/)\s*ml\b", "aiml", text, flags=re.I)


def _clean_program_candidate(text: str) -> str:
    candidate = text.strip(" ,.?")
    candidate = re.sub(r"^(compare|comparison|between|with)\b", "", candidate, flags=re.I).strip(" ,.?")
    candidate = re.sub(
        r"\b(admission|admissions|apply|application|fees|fee|eligibility|criteria|requirements|procedure|process|timeline|deadline|deadlines)\b",
        "",
        candidate,
        flags=re.I,
    )
    for alias in _CAMPUS_ALIASES:
        candidate = re.sub(rf"\b{re.escape(alias)}\b", "", candidate, flags=re.I)
    candidate = re.sub(r"\b(srm|srmist)\b", "", candidate, flags=re.I)
    candidate = re.sub(r"\s+", " ", candidate)
    candidate = candidate.strip(" ,.?")
    return candidate if _normalize_match_text(candidate) else ""


def _score_program_match(query: str, entity_name: str) -> float:
    normalized_query = _normalize_match_text(_normalize_program_text(query))
    normalized_name = _normalize_match_text(_normalize_program_text(entity_name))
    if not normalized_query or not normalized_name:
        return 0.0

    query_tokens = set(normalized_query.split())
    name_tokens = set(normalized_name.split())
    if not query_tokens or not name_tokens:
        return 0.0

    overlap = len(query_tokens & name_tokens) / max(len(query_tokens), 1)
    if overlap < 0.5:
        return 0.0

    query_degree = query_tokens & _PROGRAM_DEGREE_TOKENS
    name_degree = name_tokens & _PROGRAM_DEGREE_TOKENS
    degree_score = 0.12 if not query_degree else (0.18 if query_degree & name_degree else -0.2)
    containment_bonus = 0.3 if normalized_query in normalized_name else 0.0
    exact_prefix_bonus = 0.2 if normalized_name == normalized_query or normalized_name.startswith(f"{normalized_query} ") else 0.0
    extra_penalty = 0.03 * len(name_tokens - query_tokens)
    numeric_penalty = 0.02 * sum(token.isdigit() for token in name_tokens - query_tokens)
    return overlap + degree_score + containment_bonus + exact_prefix_bonus - extra_penalty - numeric_penalty


def _match_best_program(kg: Any, candidate: str) -> dict[str, str] | None:
    if not kg:
        return None

    cleaned_candidate = _clean_program_candidate(candidate)
    normalized_candidate = _normalize_match_text(_normalize_program_text(cleaned_candidate))
    if not normalized_candidate:
        return None

    query_tokens = set(normalized_candidate.split())
    if len(query_tokens) == 1 and query_tokens <= _PROGRAM_DEGREE_TOKENS:
        return None

    best_match: tuple[float, str, str] | None = None
    for entity in kg.entities.values():
        if entity.entity_type != "program":
            continue
        score = _score_program_match(cleaned_candidate, entity.name)
        if score < 0.62:
            continue
        candidate_tuple = (score, entity.id, entity.name)
        if best_match is None or candidate_tuple[0] > best_match[0]:
            best_match = candidate_tuple

    if best_match:
        return {"id": best_match[1], "name": best_match[2]}

    fallback = _match_program_text(kg, cleaned_candidate.lower())
    if fallback and fallback["program_id"] in kg.entities:
        entity_id = fallback["program_id"]
        return {"id": entity_id, "name": kg.entities[entity_id].name}
    return None


def _match_compare_programs(question: str, kg: Any) -> list[dict[str, str]]:
    if not kg:
        return []

    matches: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    prepared_question = _prepare_compare_text(question)
    exact_hits = []
    question_lower = _normalize_match_text(prepared_question)
    for entity in kg.entities.values():
        if entity.entity_type != "program":
            continue
        name_lower = _normalize_match_text(entity.name)
        if name_lower in question_lower:
            exact_hits.append((len(name_lower), entity.id, entity.name))
    for _, entity_id, entity_name in sorted(exact_hits, reverse=True):
        if entity_id in seen_ids:
            continue
        seen_ids.add(entity_id)
        matches.append({"id": entity_id, "name": entity_name})
        if len(matches) >= 2:
            return matches

    carry_degree = ""
    carry_context = ""
    for segment in _PROGRAM_COMPARE_SPLIT_RE.split(prepared_question):
        candidate = _clean_program_candidate(segment)
        if not candidate:
            continue
        normalized_segment = _normalize_match_text(_normalize_program_text(candidate))
        degree_tokens = [token for token in normalized_segment.split() if token in _PROGRAM_DEGREE_TOKENS]
        context_tokens = [token for token in normalized_segment.split() if token not in _PROGRAM_DEGREE_TOKENS]
        if degree_tokens:
            carry_degree = " ".join(degree_tokens)
        if context_tokens and not carry_context:
            carry_context = " ".join(context_tokens)
        if not degree_tokens and carry_degree:
            candidate = f"{carry_degree} {candidate}"
        normalized_candidate = _normalize_match_text(_normalize_program_text(candidate))

        if not _has_specific_program_hint(candidate.lower()) and not (set(normalized_candidate.split()) & _PROGRAM_DEGREE_TOKENS):
            continue

        match = _match_best_program(kg, candidate)
        if (
            carry_context
            and len(context_tokens) <= 4
            and carry_context not in normalized_candidate
        ):
            contextual_match = _match_best_program(kg, f"{carry_degree} {carry_context} {candidate}".strip())
            if contextual_match:
                match = contextual_match
        if not match:
            continue
        entity_id = match["id"]
        if entity_id in seen_ids or entity_id not in kg.entities:
            continue
        seen_ids.add(entity_id)
        matches.append({"id": entity_id, "name": match["name"]})
        if len(matches) >= 2:
            break

    if matches:
        return matches

    if _has_specific_program_hint(prepared_question.lower()):
        match = _match_best_program(kg, prepared_question)
        if match:
            return [match]
    return []


def _build_router_prompt(question: str, selected_campus: str | None, pinned_context: dict[str, Any] | None) -> str:
    prompt_parts = [
        "You are a routing classifier for an SRMIST university assistant.",
        "Return JSON only with keys: domain, task, routing_target, confidence, needs_decomposition, entities.",
        f"Allowed domains: {sorted(_ALLOWED_DOMAINS)}.",
        f"Allowed tasks: {sorted(_ALLOWED_TASKS)}.",
        f"Allowed routing_target values: {sorted(_ALLOWED_TARGETS)}.",
        "entities must be an object with optional keys campus, college, department, program, person.",
        f"Selected campus context: {selected_campus or ''}",
        f"Pinned context: {json.dumps(pinned_context or {}, ensure_ascii=False)}",
        f"Question: {question}",
    ]
    return "\n".join(prompt_parts)


def _merge_llm_fallback(
    decision: RouteDecision,
    llm_result: dict[str, Any],
) -> RouteDecision:
    domain = llm_result.get("domain")
    task = llm_result.get("task")
    target = llm_result.get("routing_target")

    if domain in _ALLOWED_DOMAINS:
        decision.domain = domain
    if task in _ALLOWED_TASKS:
        decision.task = task
    if target in _ALLOWED_TARGETS:
        decision.routing_target = target

    if isinstance(llm_result.get("needs_decomposition"), bool):
        decision.needs_decomposition = llm_result["needs_decomposition"]

    confidence = llm_result.get("confidence")
    if isinstance(confidence, (int, float)):
        decision.confidence = max(decision.confidence, min(float(confidence), 0.99))

    entities = llm_result.get("entities")
    if isinstance(entities, dict):
        for key in ("campus", "college", "department", "program", "person"):
            value = entities.get(key)
            if not value or decision.entities.get(key):
                continue
            decision.entities[key] = _normalize_campus(value) if key == "campus" else str(value).strip()

    decision.used_llm_fallback = True
    return decision


def route_query(
    question: str,
    *,
    selected_campus: str | None = None,
    pinned_context: dict[str, Any] | None = None,
    kg: Any = None,
    llm_router: Optional[Callable[[str], str]] = None,
) -> RouteDecision:
    q = question.strip()
    q_lower = q.lower()
    decision = RouteDecision()
    is_compare_query = bool(_COMPARE_RE.search(q))

    pinned_type = str((pinned_context or {}).get("type") or "").strip().lower()
    pinned_value = str((pinned_context or {}).get("display_name") or (pinned_context or {}).get("value") or "").strip()
    pinned_entity_id = str((pinned_context or {}).get("entity_id") or "").strip()

    explicit_campus = _extract_campus(q_lower)
    inferred_campus = explicit_campus or _normalize_campus(selected_campus)
    if not explicit_campus and pinned_type == "campus" and pinned_value:
        inferred_campus = _normalize_campus(pinned_value)
        decision.used_pinned_context = True
    if inferred_campus:
        decision.entities["campus"] = inferred_campus

    department_id, department_name = _find_longest_entity(
        q,
        kg,
        {"department", "school", "sub_college"},
    )
    college_id, college_name = _find_longest_entity(
        q,
        kg,
        {"college", "school", "sub_college", "directorate"},
    )

    matched_programs = _match_compare_programs(q, kg) if is_compare_query else []
    cleaned_question = _clean_program_candidate(q)
    if (
        not matched_programs
        and not _ROLE_RE.search(q)
        and not department_name
        and cleaned_question
        and _has_specific_program_hint(cleaned_question.lower())
    ):
        single_program = _match_best_program(kg, q)
        if single_program:
            matched_programs = [single_program]

    if not department_name and pinned_type == "department" and pinned_value:
        department_name = pinned_value
        department_id = pinned_entity_id or None
        decision.used_pinned_context = True
    if not matched_programs and pinned_type == "program" and pinned_value:
        matched_programs = [{"id": pinned_entity_id, "name": pinned_value}]
        decision.used_pinned_context = True

    if department_name:
        decision.entities["department"] = department_name
    if college_name:
        decision.entities["college"] = college_name
    if matched_programs:
        decision.entities["program"] = matched_programs[0]["name"]
        if len(matched_programs) > 1:
            decision.entities["programs"] = [item["name"] for item in matched_programs]
        decision.entity_ids["program"] = matched_programs[0]["id"]
        if len(matched_programs) > 1:
            decision.entity_ids["programs"] = [item["id"] for item in matched_programs]
    if department_id:
        decision.entity_ids["department"] = department_id
    if college_id:
        decision.entity_ids["college"] = college_id

    person_name = _extract_person_name(q)
    if person_name:
        decision.entities["person"] = person_name

    mentions_departments = bool(_DEPARTMENT_TERM_RE.search(q))
    mentions_programs = bool(_PROGRAM_TERM_RE.search(q))

    if _COMPARE_RE.search(q):
        decision.task = "compare"
    elif _LIST_RE.search(q):
        decision.task = "list"
    elif _ELIGIBILITY_RE.search(q):
        decision.task = "eligibility_check"
    elif _PROCEDURE_RE.search(q):
        decision.task = "procedure"
    elif _TIMELINE_RE.search(q):
        decision.task = "timeline"
    elif any((matched_programs, department_name, college_name, person_name, _ROLE_RE.search(q))):
        decision.task = "lookup"

    domain_scores = {domain: 0.0 for domain in _ALLOWED_DOMAINS}
    if _ADMISSION_RE.search(q):
        domain_scores["admissions"] += 2.0
    if _FEES_RE.search(q):
        domain_scores["fees"] += 2.0
    if _PLACEMENT_RE.search(q):
        domain_scores["placements"] += 2.0
    if _RESEARCH_RE.search(q):
        domain_scores["research"] += 2.0
    if _CAMPUS_LIFE_RE.search(q):
        domain_scores["campus_life"] += 2.0
    if _ROLE_RE.search(q) or person_name:
        domain_scores["faculty"] += 2.0
    if department_name or college_name:
        domain_scores["departments"] += 1.75
    if matched_programs:
        domain_scores["programs"] += 1.75
    if mentions_departments:
        domain_scores["departments"] += 1.5
    if mentions_programs:
        domain_scores["programs"] += 1.5

    if decision.task in {"eligibility_check", "procedure", "timeline"}:
        domain_scores["admissions"] += 1.0
    if decision.task == "compare" and matched_programs:
        domain_scores["programs"] += 0.75
        if _ADMISSION_RE.search(q) or _FEES_RE.search(q) or _ELIGIBILITY_RE.search(q):
            domain_scores["admissions"] += 0.75
    if decision.task == "list":
        if mentions_departments:
            domain_scores["departments"] += 1.0
        if mentions_programs:
            domain_scores["programs"] += 1.0

    decision.domain = max(domain_scores, key=domain_scores.get)
    if domain_scores[decision.domain] <= 0:
        decision.domain = "general"

    if decision.task == "compare":
        decision.routing_target = "comparison"
    elif decision.domain == "faculty" or _ROLE_RE.search(q):
        decision.routing_target = "kg_role"
    elif decision.task == "list" and (department_name or college_name or mentions_departments or mentions_programs):
        decision.routing_target = "kg_listing"
    elif decision.domain in {"admissions", "fees"} or decision.task in {"eligibility_check", "procedure", "timeline"}:
        decision.routing_target = "admissions"
    else:
        decision.routing_target = "retrieval"

    decision.needs_decomposition = (
        decision.task == "compare"
        or len(matched_programs) > 1
        or sum(
            bool(pattern.search(q))
            for pattern in (_FEES_RE, _ELIGIBILITY_RE, _PROCEDURE_RE, _TIMELINE_RE)
        ) > 1
    )

    confidence = 0.25
    if decision.domain != "general":
        confidence += 0.2
    if decision.task != "general":
        confidence += 0.2
    if decision.entities:
        confidence += 0.2
    if decision.routing_target != "retrieval":
        confidence += 0.1
    if decision.needs_decomposition:
        confidence += 0.05
    if decision.used_pinned_context:
        confidence += 0.05
    decision.confidence = min(confidence, 0.95)

    if llm_router and (decision.confidence < 0.55 or decision.domain == "general" or decision.task == "general"):
        llm_response = llm_router(_build_router_prompt(q, inferred_campus, pinned_context))
        llm_result = _extract_json_object(llm_response)
        if llm_result:
            decision = _merge_llm_fallback(decision, llm_result)

    return decision
