from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.query_router import RouteDecision

_FEES_RE = re.compile(r"\b(fee|fees|tuition|cost)\b", re.I)
_ELIGIBILITY_RE = re.compile(r"\b(eligible|eligibility|criteria|requirements?)\b", re.I)
_PROCEDURE_RE = re.compile(r"\b(how to|apply|application|steps|process|procedure)\b", re.I)
_TIMELINE_RE = re.compile(r"\b(date|dates|deadline|timeline|schedule|last date|when)\b", re.I)
_ROUTE_RE = re.compile(r"\b(admission|admissions|route|entrance|srmjeee|how to apply)\b", re.I)

_RESPONSE_SHAPES = {
    "list": "list",
    "compare": "comparison",
    "eligibility_check": "eligibility",
    "procedure": "procedure",
    "timeline": "procedure",
    "lookup": "direct",
    "general": "direct",
}


@dataclass
class DecompositionStep:
    step_type: str
    label: str
    retrieval_query: str
    focus: str | None = None
    entity_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnswerPlan:
    query_summary: str
    response_shape: str
    required_facts: list[str] = field(default_factory=list)
    resolved_entities: dict[str, Any] = field(default_factory=dict)
    evidence_targets: list[str] = field(default_factory=list)
    missing_info: list[str] = field(default_factory=list)
    candidate_items: list[str] = field(default_factory=list)
    comparison_axes: list[str] = field(default_factory=list)
    decomposition_steps: list[DecompositionStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["decomposition_steps"] = [step.to_dict() for step in self.decomposition_steps]
        return payload

    def to_prompt_block(self) -> str:
        lines = [
            f"Response shape: {self.response_shape}",
            f"Required facts: {', '.join(self.required_facts) if self.required_facts else 'none'}",
            f"Resolved entities: {self.resolved_entities or {}}",
            f"Evidence targets: {', '.join(self.evidence_targets) if self.evidence_targets else 'none'}",
        ]
        if self.candidate_items:
            lines.append("Candidate items: " + "; ".join(self.candidate_items[:20]))
        if self.comparison_axes:
            lines.append("Comparison axes: " + ", ".join(self.comparison_axes))
        if self.missing_info:
            lines.append("Missing info: " + ", ".join(self.missing_info))
        if self.decomposition_steps:
            lines.append(
                "Decomposition steps: " + " | ".join(
                    f"{step.label} -> {step.retrieval_query}" for step in self.decomposition_steps
                )
            )
        return "\n".join(lines)


def _extract_axes(question: str) -> list[str]:
    axes: list[str] = []
    if _ROUTE_RE.search(question):
        axes.append("admission_route")
    if _FEES_RE.search(question):
        axes.append("fees")
    if _ELIGIBILITY_RE.search(question):
        axes.append("eligibility")
    if _PROCEDURE_RE.search(question):
        axes.append("procedure")
    if _TIMELINE_RE.search(question):
        axes.append("timeline")
    return axes


def _collect_candidate_items(route: RouteDecision, kg: Any) -> list[str]:
    if not kg:
        return []

    parent_candidates = [
        route.entity_ids.get("department"),
        route.entity_ids.get("college"),
    ]
    for parent_id in parent_candidates:
        if not parent_id:
            continue

        relation_orders = (
            ("offers_program", "has_department", "has_sub_college", "has_centre", None)
            if str(parent_id).startswith("department--")
            else ("has_department", "has_sub_college", "offers_program", "has_centre", None)
        )
        for relation in relation_orders:
            children = kg.get_children(parent_id, relation)
            if children:
                return [child.name for child in children]
    return []


def build_answer_plan(
    question: str,
    route: RouteDecision,
    *,
    kg: Any = None,
) -> AnswerPlan:
    response_shape = _RESPONSE_SHAPES.get(route.task, "direct")
    axes = _extract_axes(question)
    evidence_targets = axes.copy()
    required_facts = axes.copy()
    if not required_facts:
        required_facts = [route.domain, route.task]

    candidate_items = _collect_candidate_items(route, kg) if route.task == "list" else []
    comparison_subjects = route.entities.get("programs") or []
    if not comparison_subjects and route.entities.get("program"):
        comparison_subjects = [route.entities["program"]]

    decomposition_steps: list[DecompositionStep] = []
    if route.task == "compare":
        comparison_axes = axes or ["overview"]
        for subject in comparison_subjects:
            decomposition_steps.append(
                DecompositionStep(
                    step_type="entity_lookup",
                    label=f"Gather evidence for {subject}",
                    retrieval_query=" ".join(
                        part for part in [subject, route.entities.get("campus", ""), " ".join(comparison_axes)] if part
                    ),
                    focus="comparison",
                    entity_name=subject,
                )
            )
        if len(comparison_subjects) >= 2:
            decomposition_steps.append(
                DecompositionStep(
                    step_type="comparison_merge",
                    label="Gather direct comparison evidence",
                    retrieval_query=" ".join(
                        part for part in [question, route.entities.get("campus", "")] if part
                    ).strip(),
                    focus="comparison",
                )
            )
    elif route.needs_decomposition and axes:
        for axis in axes:
            decomposition_steps.append(
                DecompositionStep(
                    step_type="field_lookup",
                    label=f"Gather {axis.replace('_', ' ')} evidence",
                    retrieval_query=" ".join(
                        part for part in [question, axis.replace("_", " "), route.entities.get("campus", "")] if part
                    ).strip(),
                    focus=axis,
                    entity_name=route.entities.get("program") or route.entities.get("department"),
                )
            )

    missing_info: list[str] = []
    if route.task == "compare" and len(comparison_subjects) < 2:
        missing_info.append("second comparison subject")
    if route.task in {"eligibility_check", "procedure", "timeline"} and route.domain == "admissions":
        if not route.entities.get("program") and not route.entities.get("college"):
            missing_info.append("specific program or faculty scope")

    return AnswerPlan(
        query_summary=question.strip(),
        response_shape=response_shape,
        required_facts=required_facts,
        resolved_entities={k: v for k, v in route.entities.items() if v},
        evidence_targets=evidence_targets,
        missing_info=missing_info,
        candidate_items=candidate_items,
        comparison_axes=axes,
        decomposition_steps=decomposition_steps,
    )
