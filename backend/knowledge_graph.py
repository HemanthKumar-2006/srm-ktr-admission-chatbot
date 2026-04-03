"""
Lightweight Knowledge Graph for SRMIST entities — v2.

Builds an in-memory entity-relationship graph from scraped SRM data and a set
of hardcoded seed nodes that form the stable institutional skeleton.

Schema (entity_type):
    university | campus | college | sub_college | department | centre |
    directorate | program | facility | admission | publication | misc

Relationships (relation_type):
    has_campus | has_college | has_sub_college | has_department | has_centre |
    has_directorate | has_facility | offers_program | has_admission |
    admission_governs | collaborates_with | also_listed_under | belongs_to

See KG_GUIDELINE.md at the project root for the full schema definition,
naming conventions, and update rules.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

log = logging.getLogger("srm_chatbot.kg")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Entity:
    id: str
    name: str
    entity_type: str   # see module docstring for full list
    campus: str = "KTR"
    url: str = ""
    attributes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Entity:
        return cls(**d)


@dataclass
class Relationship:
    source_id: str
    target_id: str
    relation_type: str   # see module docstring for full list
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Relationship:
        # metadata field may be absent in older JSON — default to {}
        d.setdefault("metadata", {})
        return cls(**d)


# ---------------------------------------------------------------------------
# Seed data — canonical institutional skeleton
# See KG_GUIDELINE.md §6 for the rationale and update rules.
# ---------------------------------------------------------------------------

SEED_UNIVERSITY = {
    "id": "university--srmist",
    "name": "SRMIST",
    "entity_type": "university",
    "campus": "",
    "url": "https://www.srmist.edu.in/",
}

SEED_CAMPUSES = [
    {"id": "campus--kattankulathur", "name": "Kattankulathur", "campus": "KTR",
     "url": "https://www.srmist.edu.in/"},
    {"id": "campus--ramapuram",      "name": "Ramapuram",      "campus": "Ramapuram",
     "url": ""},
    {"id": "campus--vadapalani",     "name": "Vadapalani",     "campus": "Vadapalani",
     "url": ""},
]

# Colleges under Kattankulathur
SEED_KTR_COLLEGES = [
    {
        "id": "college--faculty-of-engineering-and-technology",
        "name": "Faculty of Engineering & Technology",
        "url": "https://www.srmist.edu.in/college/college-of-engineering-technology/",
    },
    {
        "id": "college--faculty-of-science-and-humanities",
        "name": "Faculty of Science & Humanities",
        "url": "https://www.srmist.edu.in/college/college-of-science-and-humanities/",
    },
    {
        "id": "college--medicine-and-health-sciences",
        "name": "Medicine & Health Sciences",
        "url": "https://www.srmist.edu.in/college/medicine-and-health-sciences/",
    },
    {
        "id": "college--college-of-agricultural-sciences",
        "name": "College of Agricultural Sciences",
        "url": "https://www.srmist.edu.in/department/college-of-agriculture-sciences/",
    },
    {
        "id": "college--srm-school-of-law",
        "name": "SRM School of Law",
        "url": "https://www.srmist.edu.in/college/college-of-law/",
    },
    {
        "id": "college--faculty-of-management",
        "name": "Faculty of Management",
        "url": "https://www.srmist.edu.in/faculty-of-management/",
    },
]

# Map scraped URL slugs to canonical seed college IDs.
# Scraped pages arrive with slugs like "college-of-engineering-technology" but
# the seed uses "faculty-of-engineering-and-technology". Without this map the
# builder creates a duplicate college entity.
_COLLEGE_URL_SLUG_TO_SEED: dict[str, str] = {
    "college-of-engineering-technology":  "college--faculty-of-engineering-and-technology",
    "college-of-science-and-humanities":  "college--faculty-of-science-and-humanities",
    "college-of-law":                     "college--srm-school-of-law",
    "college-of-management":             "college--faculty-of-management",
    "agriculture-sciences":              "college--college-of-agricultural-sciences",
}

# Sub-colleges within Medicine & Health Sciences
SEED_MEDICINE_SUB_COLLEGES = [
    {"id": "sub_college--college-of-medicine",             "name": "College of Medicine"},
    {"id": "sub_college--college-of-dentistry",            "name": "College of Dentistry"},
    {"id": "sub_college--college-of-pharmacy",             "name": "College of Pharmacy"},
    {"id": "sub_college--college-of-physiotherapy",        "name": "College of Physiotherapy"},
    {"id": "sub_college--college-of-occupational-therapy", "name": "College of Occupational Therapy"},
    {"id": "sub_college--college-of-nursing",              "name": "College of Nursing"},
    {"id": "sub_college--school-of-public-health",         "name": "School of Public Health"},
]

# Slugs that match sub-colleges — these arrive as /department/{slug}/ URLs
# but should NOT create new department entities (they duplicate the sub_college).
_SUB_COLLEGE_DEPT_SLUGS: set[str] = {
    "college-of-nursing",
    "college-of-pharmacy",
    "college-of-physiotherapy",
    "college-of-occupational-therapy",
    "school-of-public-health",
}

# ---------------------------------------------------------------------------
# FET (Faculty of Engineering & Technology) — Schools, Depts, Centres
# ---------------------------------------------------------------------------
_FET = "college--faculty-of-engineering-and-technology"

SEED_FET_SCHOOLS = [
    {"id": "school--school-of-computing",                          "name": "School of Computing"},
    {"id": "school--school-of-bio-engineering",                    "name": "School of Bio-Engineering"},
    {"id": "school--school-of-electrical-and-electronics-engineering", "name": "School of Electrical and Electronics Engineering"},
    {"id": "school--school-of-mechanical-engineering",             "name": "School of Mechanical Engineering"},
    {"id": "school--school-of-civil-engineering",                  "name": "School of Civil Engineering"},
    {"id": "school--school-of-architecture-and-interior-design",   "name": "School of Architecture and Interior Design"},
    {"id": "school--school-of-basic-sciences",                     "name": "School of Basic Sciences"},
]

# school_id → list of department slugs (the part after "department-of-" or full slug)
SEED_FET_SCHOOL_DEPTS: dict[str, list[str]] = {
    "school--school-of-computing": [
        "department-of-computing-technologies",
        "department-of-computational-intelligence",
        "department-of-data-science-and-business-systems",
        "department-of-networking-and-communications",
    ],
    "school--school-of-bio-engineering": [
        "department-of-biomedical-engineering",
        "department-of-biotechnology",
        "department-of-genetic-engineering",
        "department-of-chemical-engineering",
        "department-of-food-technology",
    ],
    "school--school-of-electrical-and-electronics-engineering": [
        "department-of-electrical-and-electronics-engineering",
        "department-of-electronics-communication",
        "department-of-electronics-instrumentation",
    ],
    "school--school-of-mechanical-engineering": [
        "department-of-mechanical-engineering",
        "department-of-aerospace-engineering",
        "department-of-automobile-engineering",
        "department-of-mechatronics",
    ],
    "school--school-of-civil-engineering": [
        "department-of-civil-engineering",
    ],
    "school--school-of-architecture-and-interior-design": [
        "department-of-architecture",
    ],
    "school--school-of-basic-sciences": [
        "department-of-chemistry",
        "department-of-mathematics",
        "department-of-physics-and-nanotechnology",
        "department-of-language-culture-and-society",
    ],
}

# Centres under FET (entity_type = "centre")
SEED_FET_CENTRES = [
    {"id": "centre--center-for-architectural-heritage",         "name": "Center for Architectural Heritage"},
    {"id": "centre--cdc-cet",                                   "name": "Career Development Centre (CET)"},
    {"id": "centre--srm-dbt-platform",                          "name": "SRM-DBT Platform"},
    {"id": "centre--cacr",                                      "name": "Centre For Advanced Concrete Research (CACR)"},
    {"id": "centre--nanotechnology-research-center",            "name": "Nanotechnology Research Center"},
    {"id": "centre--centre-for-yoga",                           "name": "Centre for Yoga"},
    {"id": "centre--centre-for-composites-and-advanced-materials", "name": "Centre for Composites and Advanced Materials"},
    {"id": "centre--srm-brin-centre",                           "name": "SRM BRIN Centre (Center of Excellence in Automation Technologies)"},
    {"id": "centre--center-for-immersive-technologies",         "name": "Center for Immersive Technologies"},
    {"id": "centre--tropic",                                    "name": "CenTRe for atmOsPheric scIences and Climate studies (TROPIC)"},
    {"id": "centre--cesd",                                      "name": "Center for Electronics and Skill Development and Consultancy Services"},
    {"id": "centre--coe-electronic-cooling-cfd",                "name": "Center of Excellence for Electronic Cooling and CFD Simulation"},
    {"id": "centre--centre-for-electric-mobility",              "name": "Centre for Electric Mobility"},
    {"id": "centre--cemat",                                     "name": "Center of Excellence in Materials for Advanced Technologies (CeMAT)"},
    {"id": "centre--dr-trp-multidisciplinary-research-centre",  "name": "Dr. T. R. Paarivendhar Multidisciplinary Research Centre"},
    {"id": "centre--camera",                                    "name": "Centre for Analysis of Movement, Ergonomics Research and Animersion"},
    {"id": "centre--cacts",                                     "name": "Centre for Advanced Computational and Theoretical Sciences"},
]

# ---------------------------------------------------------------------------
# CSH (Faculty of Science & Humanities) — Departments, Centre
# ---------------------------------------------------------------------------
_CSH = "college--faculty-of-science-and-humanities"

# Department slugs that belong to CSH
SEED_CSH_DEPT_SLUGS: list[str] = [
    "department-of-biochemistry",
    "department-of-biotechnology-science-and-humanities",
    "department-of-commerce",
    "department-of-computer-applications",
    "department-of-computer-science",
    "department-of-corporate-secretaryship-and-accounting-finance",
    "department-of-defence-and-strategic-studies",
    "department-of-economics",
    "department-of-english",
    "department-of-fashion-designing",
    "department-of-french",
    "department-of-hindi",
    "department-of-journalism-and-mass-communication",
    "department-of-mathematics-and-statistics",
    "department-of-physical-education-sports-sciences",
    "department-of-psychology",
    "department-of-social-work",
    "department-of-tamil",
    "department-of-visual-communication",
    "department-of-yoga",
    "school-of-education",
    "institute-of-hotel-and-catering-management",
]

SEED_CSH_CENTRES = [
    {"id": "centre--cdc-csh", "name": "Career Development Centre (CSH)"},
]

# ---------------------------------------------------------------------------
# Directorates, Facilities, Admissions, Publications, Misc
# ---------------------------------------------------------------------------

# Directorates under Kattankulathur campus
SEED_KTR_DIRECTORATES = [
    {
        "id": "directorate--directorate-of-research",
        "name": "Directorate of Research",
        "url": "",
    },
    {
        "id": "directorate--controller-of-examinations",
        "name": "Controller of Examinations",
        "url": "",
    },
    {
        "id": "directorate--directorate-of-alumni-affairs",
        "name": "Directorate of Alumni Affairs",
        "url": "",
    },
    {
        "id": "directorate--directorate-of-communications",
        "name": "Directorate of Communications",
        "url": "",
    },
    {
        "id": "directorate--directorate-of-career-centre",
        "name": "Directorate of Career Centre",
        "url": "",
    },
    {
        "id": "directorate--itkm",
        "name": "Information Technology and Knowledge Management (ITKM)",
        "url": "",
    },
    {
        "id": "directorate--directorate-of-learning-and-development",
        "name": "Directorate of Learning and Development",
        "url": "",
    },
    {
        "id": "directorate--directorate-of-campus-administration",
        "name": "Directorate of Campus Administration & Facilities",
        "url": "",
    },
    {
        "id": "directorate--directorate-of-distance-education",
        "name": "Directorate of Distance Education",
        "url": "",
    },
    {
        "id": "directorate--directorate-of-online-education",
        "name": "Directorate of Online Education",
        "url": "",
    },
]

# Physical / operational facilities under Kattankulathur
SEED_KTR_FACILITIES = [
    {"id": "facility--housing",     "name": "Housing & Residential",
     "url": ""},
    {"id": "facility--transport",   "name": "Transport",
     "url": ""},
    {"id": "facility--srm-hotels",  "name": "SRM Hotels",
     "url": ""},
    {"id": "facility--library",     "name": "Library",
     "url": ""},
]

# Admission portal nodes
SEED_ADMISSIONS = [
    {
        "id": "admission--india",
        "name": "Admissions — India",
        "url": "https://www.srmist.edu.in/admission-india/",
    },
    {
        "id": "admission--international",
        "name": "Admissions — International",
        "url": "https://www.srmist.edu.in/admission-international/",
    },
]

# Publications / achievements
SEED_PUBLICATIONS = [
    {
        "id": "publication--publications",
        "name": "Publications",
        "url": "https://www.srmist.edu.in/publications/",
    },
    {
        "id": "publication--faculty-achievements",
        "name": "Faculty Achievements",
        "url": "https://www.srmist.edu.in/faculty-gateway/faculty-achivements/",
    },
]

# Miscellaneous utility pages
SEED_MISC = [
    {"id": "misc--news-and-events", "name": "News & Events",    "url": ""},
    {"id": "misc--blog",            "name": "Blog",             "url": ""},
    {"id": "misc--careers-at-srm",  "name": "Careers at SRM",  "url": ""},
    {"id": "misc--about-srmist",    "name": "About SRMIST",     "url": ""},
    {"id": "misc--contact",         "name": "Contact",          "url": ""},
]

# Cross-links: (source_id, target_id, relation_type)
# These supplement the primary has_* relationships.
SEED_CROSS_LINKS = [
    # Housing and Transport also sit under Campus Life context
    ("facility--housing",   "campus--kattankulathur", "also_listed_under"),
    ("facility--transport", "campus--kattankulathur", "also_listed_under"),
    # Controller of Examinations is linked to Admissions
    ("directorate--controller-of-examinations", "admission--india",          "also_listed_under"),
    ("directorate--controller-of-examinations", "admission--international",   "also_listed_under"),
    # Directorate of Research collaborates with Engg & Science colleges
    (
        "directorate--directorate-of-research",
        "college--faculty-of-engineering-and-technology",
        "collaborates_with",
    ),
    (
        "directorate--directorate-of-research",
        "college--faculty-of-science-and-humanities",
        "collaborates_with",
    ),
    # CDC centres co-owned by Directorate of Career Centre + respective college
    ("directorate--directorate-of-career-centre", "centre--cdc-cet", "has_centre"),
    ("directorate--directorate-of-career-centre", "centre--cdc-csh", "has_centre"),
]

# ---------------------------------------------------------------------------
# Deduplication / cleanup constants
# ---------------------------------------------------------------------------

# Department slugs that are NOT real departments — skip during build.
_DEPT_SLUG_BLOCKLIST: set[str] = {
    "achievements",
    "librarian",
    "publications-2022-23",
    "publications-2023-24",
    "research-2",
    "research",
    "som",
    "cesd",
    # Sub-college duplicates (these arrive as /department/ URLs)
    "college-of-agriculture-sciences",
    "college-of-nursing",
    "college-of-pharmacy",
    "college-of-physiotherapy",
    "college-of-occupational-therapy",
    "school-of-public-health",
    # CDC pages — handled as centres, not departments
    "cdc-csh",
    "cet-cdc",
}

# Department slugs that should be dropped because they duplicate another entity.
_DEPT_SLUG_MERGE: dict[str, str | None] = {
    # chemistry-2 is a duplicate/garbage entry → drop
    "department-of-chemistry-2": None,
    # mathematics-2 is a duplicate → drop
    "department-of-mathematics-2": None,
    # department-of-physics duplicates department-of-physics-and-nanotechnology
    "department-of-physics": "department--department-of-physics-and-nanotechnology",
}

# All department slugs that belong to FET (flattened from SEED_FET_SCHOOL_DEPTS)
_FET_DEPT_SLUGS: set[str] = set()
for _dept_list in SEED_FET_SCHOOL_DEPTS.values():
    _FET_DEPT_SLUGS.update(_dept_list)

# All department slugs that belong to CSH
_CSH_DEPT_SLUGS: set[str] = set(SEED_CSH_DEPT_SLUGS)

# All known centre slugs under FET (for reclassification)
_FET_CENTRE_SLUGS: set[str] = set()
for _c in SEED_FET_CENTRES:
    # Extract the slug portion from the centre ID
    _FET_CENTRE_SLUGS.add(_c["id"].replace("centre--", ""))


# ---------------------------------------------------------------------------
# URL-to-slug helpers
# ---------------------------------------------------------------------------

_STRIP_DOMAIN   = re.compile(r"^https?://(?:www\.)?srmist\.edu\.in")
_TRAILING_SLASH = re.compile(r"/+$")


def _url_to_slug(url: str) -> str:
    """Turn a canonical URL into a stable entity ID slug."""
    path = _STRIP_DOMAIN.sub("", url.lower())
    path = _TRAILING_SLASH.sub("", path).strip("/")
    return path.replace("/", "--")


def _slug_to_readable(slug: str) -> str:
    """Convert 'department--department-of-computer-science' -> 'Computer Science'."""
    last = slug.split("--")[-1]
    for prefix in ("department-of-", "college-of-", "school-of-", "program-", "faculty-of-"):
        if last.startswith(prefix):
            last = last[len(prefix):]
            break
    return last.replace("-", " ").strip().title()


# ---------------------------------------------------------------------------
# Content-parsing regexes
# ---------------------------------------------------------------------------

# Person-name pattern: requires honorific (Dr/Prof/Mr/Mrs/Ms) followed by
# a proper name (initial-dotted tokens + surname, e.g. "K. Srinivasan" or
# "Muthulakshmi P").  The honorific constraint prevents matching general text
# like "Welcome message …" that happens to follow "Head of Department".
_PERSON_NAME_RE = (
    r"(?:Dr\.?\s*|Prof\.?\s*|Mr\.?\s*|Mrs\.?\s*|Ms\.?\s*)"
    r"([A-Z][A-Za-z.\-' ]{1,38}[A-Za-z.])"
)

_HOD_PATTERN = re.compile(
    r"(?:Head\s+of\s+(?:the\s+)?Department|HoD|HOD)\s*[:\-–]?\s*"
    + _PERSON_NAME_RE,
    re.I,
)

_DEAN_PATTERN = re.compile(
    r"(?:Dean)\s*[:\-–]?\s*"
    + _PERSON_NAME_RE,
    re.I,
)

_CHAIRPERSON_PATTERN = re.compile(
    r"(?:Chairperson|Chair)\s*[:\-–]?\s*"
    + _PERSON_NAME_RE,
    re.I,
)

_MEET_HOD_PATTERN = re.compile(
    r"(?:Dr\.?\s*|Prof\.?\s*)([A-Z][A-Za-z.\-' ]{2,40}?)\s+"
    r"(?:Professor\s*&?\s*|Associate\s+Professor\s*&?\s*|Research\s+(?:Professor|Associate\s+Professor)\s*&?\s*)?"
    r"Head\s+"
    r"([A-Za-z &,.\-]+?)(?:\s+Dr\.|\s+Prof\.|\s+School|\s+Pioneering|$)",
    re.I,
)

_MEET_CHAIR_PATTERN = re.compile(
    r"(?:Dr\.?\s*|Prof\.?\s*)([A-Z][A-Za-z.\-' ]{2,40}?)\s+"
    r"(?:Professor\s*&?\s*|Associate\s+Professor\s*&?\s*)?"
    r"Chairperson\s+"
    r"([A-Za-z &,.\-]+?)(?:\s+Dr\.|\s+Prof\.|\s+School|\s+Pioneering|$)",
    re.I,
)

_CAMPUS_PATTERNS = [
    (re.compile(r"\bkattankulathur\b|\bktr\b", re.I), "KTR"),
    (re.compile(r"\bramapuram\b|\brmp\b", re.I), "Ramapuram"),
    (re.compile(r"\bvadapalani\b|\bvdp\b", re.I), "Vadapalani"),
    (re.compile(r"\bghaziabad\b|\bdelhi[\s-]?ncr\b|\bncr\b", re.I), "Delhi-NCR"),
    (re.compile(r"\btiruchirappalli\b|\btrichy\b", re.I), "Tiruchirappalli"),
]


def _detect_campus(url: str, content: str) -> str:
    text = f"{url} {content[:500]}"
    for pat, campus in _CAMPUS_PATTERNS:
        if pat.search(text):
            return campus
    return "KTR"


# ---------------------------------------------------------------------------
# URL pattern matchers
# ---------------------------------------------------------------------------

_COLLEGE_ROOT_RE = re.compile(
    r"^https?://(?:www\.)?srmist\.edu\.in/college/([^/]+)/?$"
)
_DEPT_ROOT_RE = re.compile(
    r"^https?://(?:www\.)?srmist\.edu\.in/department/([^/]+)/?$"
)
_DEPT_SUBPAGE_RE = re.compile(
    r"^https?://(?:www\.)?srmist\.edu\.in/department/([^/]+)/([^/]+)/?$"
)
_PROGRAM_RE = re.compile(
    r"^https?://(?:www\.)?srmist\.edu\.in/program/([^/]+)/?$"
)
_COLLEGE_SUBPAGE_RE = re.compile(
    r"^https?://(?:www\.)?srmist\.edu\.in/college/([^/]+)/([^/]+)/?$"
)
_CENTRE_RE = re.compile(
    r"^https?://(?:www\.)?srmist\.edu\.in/(?:centre|center|centers)/([^/]+)/?$",
    re.I,
)
_DIRECTORATE_RE = re.compile(
    r"^https?://(?:www\.)?srmist\.edu\.in/directorate/([^/]+)/?$",
    re.I,
)
_LAB_RE = re.compile(
    r"^https?://(?:www\.)?srmist\.edu\.in/lab/([^/]+)/?$",
    re.I,
)
_ADMISSION_RE = re.compile(
    r"^https?://(?:www\.)?srmist\.edu\.in/admission-(india|international)/?$",
    re.I,
)
_PUBLICATION_RE = re.compile(
    r"srmist\.edu\.in/(publications|faculty-gateway)/?",
    re.I,
)


# ---------------------------------------------------------------------------
# Slug classification helpers
# ---------------------------------------------------------------------------

# Keywords that indicate a URL slug represents a centre/lab rather than a
# department (used to reclassify /department/{slug}/ pages).
_CENTRE_KEYWORDS = {
    "centre", "center", "coe", "lab", "laboratory", "research-centre",
    "research-center", "platform", "brin", "tropic", "cesd", "cemat",
    "cacr", "camera", "cacts", "nanotechnology-research",
    "immersive-technologies", "electric-mobility", "composites",
    "multidisciplinary-research", "electronic-cooling",
}


def _is_centre_slug(slug: str) -> bool:
    """Return True if the URL slug looks like a centre/lab rather than a department."""
    slug_lower = slug.lower()
    # Check if slug is a known FET centre
    if slug_lower in _FET_CENTRE_SLUGS:
        return True
    # Check if any centre keyword appears in the slug
    return any(kw in slug_lower for kw in _CENTRE_KEYWORDS)


def _enforce_single_parent(kg: KnowledgeGraph) -> None:
    """
    Ensure that each department/program has exactly ONE parent relationship.
    When multiple parents exist (e.g. from both seed and scraped link inference),
    keep the most specific parent (prefer school > college > campus).

    Uses object identity (id()) to avoid accidentally removing a kept relationship
    whose (source, target, type) tuple duplicates one in the to-remove set.
    """
    _parent_rel_types = {"has_department", "offers_program"}
    _parent_priority = {
        "school": 3, "department": 2, "college": 1,
        "sub_college": 1, "campus": 0, "university": 0,
    }

    # Group parent relationships by target — deduplicate by (source, target, type) first
    target_parents: dict[str, list[Relationship]] = {}
    seen_keys: dict[str, set[tuple[str, str, str]]] = {}
    for r in kg.relationships:
        if r.relation_type in _parent_rel_types:
            key = (r.source_id, r.target_id, r.relation_type)
            seen_set = seen_keys.setdefault(r.target_id, set())
            if key not in seen_set:
                seen_set.add(key)
                target_parents.setdefault(r.target_id, []).append(r)

    # For each target with multiple DISTINCT parents, pick the best one
    to_keep_ids: set[int] = set()
    contested_targets: set[str] = set()
    for target_id, rels in target_parents.items():
        if len(rels) <= 1:
            continue
        contested_targets.add(target_id)

        def _priority(r: Relationship) -> int:
            parent = kg.entities.get(r.source_id)
            if not parent:
                return -1
            return _parent_priority.get(parent.entity_type, 0)

        best = max(rels, key=_priority)
        to_keep_ids.add(id(best))

    if not contested_targets:
        return

    # Rebuild: keep only the winning parent rel for contested targets;
    # remove ALL other has_department/offers_program rels pointing to them.
    new_rels: list[Relationship] = []
    removed = 0
    for r in kg.relationships:
        if r.relation_type in _parent_rel_types and r.target_id in contested_targets:
            if id(r) in to_keep_ids:
                new_rels.append(r)
            else:
                removed += 1
        else:
            new_rels.append(r)

    kg.relationships = new_rels
    if removed:
        log.info(f"Enforced single-parent: removed {removed} duplicate parent links")


# ---------------------------------------------------------------------------
# KnowledgeGraph
# ---------------------------------------------------------------------------

class KnowledgeGraph:

    def __init__(self):
        self.entities: dict[str, Entity] = {}
        self.relationships: list[Relationship] = []
        self._children_idx: dict[str, list[str]] = {}   # source_id -> [target_ids]
        self._parent_idx: dict[str, str] = {}            # target_id -> source_id
        self._name_idx: dict[str, str] = {}              # lowered name -> entity id

    # ----- mutation -----

    def add_entity(self, entity: Entity) -> None:
        self.entities[entity.id] = entity
        self._name_idx[entity.name.lower()] = entity.id

    def add_relationship(self, rel: Relationship) -> None:
        self.relationships.append(rel)
        self._children_idx.setdefault(rel.source_id, []).append(rel.target_id)
        _parent_rel_types = {
            "has_campus", "has_college", "has_sub_college",
            "has_department", "has_centre", "has_directorate",
            "has_facility", "belongs_to",
        }
        if rel.relation_type in _parent_rel_types:
            self._parent_idx[rel.target_id] = rel.source_id

    # ----- queries -----

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        return self.entities.get(entity_id)

    def get_children(
        self,
        entity_id: str,
        relation_type: Optional[str] = None,
    ) -> list[Entity]:
        child_ids = self._children_idx.get(entity_id, [])
        if relation_type:
            child_ids = [
                cid for cid in child_ids
                if any(
                    r.target_id == cid
                    and r.source_id == entity_id
                    and r.relation_type == relation_type
                    for r in self.relationships
                )
            ]
        return [self.entities[cid] for cid in child_ids if cid in self.entities]

    def get_parent(self, entity_id: str) -> Optional[Entity]:
        pid = self._parent_idx.get(entity_id)
        return self.entities.get(pid) if pid else None

    def search_entities(
        self,
        query: str,
        entity_type: Optional[str] = None,
    ) -> list[Entity]:
        """Fuzzy name search: returns entities whose name contains all query tokens."""
        tokens = query.lower().split()
        results = []
        for ent in self.entities.values():
            if entity_type and ent.entity_type != entity_type:
                continue
            name_low = ent.name.lower()
            all_attrs = " ".join(str(v) for v in ent.attributes.values()).lower()
            combined = f"{name_low} {all_attrs}"
            if all(t in combined for t in tokens):
                results.append(ent)
        return results

    def get_entity_by_name(self, name: str) -> Optional[Entity]:
        eid = self._name_idx.get(name.lower())
        return self.entities.get(eid) if eid else None

    def find_entity_fuzzy(
        self, text: str, entity_type: Optional[str] = None
    ) -> Optional[Entity]:
        """Find best-matching entity by checking if entity name appears in text."""
        text_lower = text.lower()
        best: Optional[Entity] = None
        best_len = 0
        for ent in self.entities.values():
            if entity_type and ent.entity_type != entity_type:
                continue
            if ent.name.lower() in text_lower and len(ent.name) > best_len:
                best = ent
                best_len = len(ent.name)
        return best

    # ----- high-level answer helpers -----

    def answer_listing_query(self, question: str) -> Optional[str]:
        """Try to answer 'What departments under X?' style questions from KG."""
        # Normalize common variations: "and" ↔ "&", extra whitespace
        q = question.lower().replace(" & ", " and ").replace("&", " and ")
        q = " ".join(q.split())  # collapse whitespace

        target_entity = None
        for ent in sorted(self.entities.values(), key=lambda e: -len(e.name)):
            name_normalized = ent.name.lower().replace(" & ", " and ").replace("&", " and ")
            if name_normalized in q and ent.entity_type in (
                "school", "college", "sub_college", "directorate"
            ):
                target_entity = ent
                break

        if not target_entity:
            return None

        # Try a sequence of progressively broader child lookups
        children: list[Entity] = []
        for rel in ("has_department", "has_sub_college", "has_centre", None):
            children = self.get_children(target_entity.id, rel)
            if children:
                break

        if not children:
            return None

        lines = [f"According to SRMIST records, {target_entity.name} includes:"]
        for child in sorted(children, key=lambda c: c.name):
            hod = child.attributes.get("hod", "")
            suffix = f" (HOD: {hod})" if hod else ""
            lines.append(f"- {child.name}{suffix}")

        return "\n".join(lines)

    def answer_role_query(self, question: str) -> Optional[str]:
        """Try to answer 'Who is HOD/Dean of X?' from KG attributes."""
        q = question.lower().replace(" & ", " and ").replace("&", " and ")
        q = " ".join(q.split())

        target_entity = None
        for ent in sorted(self.entities.values(), key=lambda e: -len(e.name)):
            name_normalized = ent.name.lower().replace(" & ", " and ").replace("&", " and ")
            if name_normalized in q and ent.entity_type in (
                "department", "school", "college", "sub_college", "directorate"
            ):
                target_entity = ent
                break

        if not target_entity:
            return None

        hod         = target_entity.attributes.get("hod")
        chairperson = target_entity.attributes.get("chairperson")
        dean        = target_entity.attributes.get("dean")

        parts = []
        if "hod" in q or "head" in q or "head of department" in q:
            if hod:
                parts.append(f"The Head of {target_entity.name} is {hod}.")
        if "dean" in q:
            if dean:
                parts.append(f"The Dean of {target_entity.name} is {dean}.")
        if "chair" in q:
            if chairperson:
                parts.append(f"The Chairperson of {target_entity.name} is {chairperson}.")

        if not parts:
            for role_key, role_label in [
                ("hod", "HOD"), ("chairperson", "Chairperson"), ("dean", "Dean")
            ]:
                val = target_entity.attributes.get(role_key)
                if val:
                    parts.append(f"The {role_label} of {target_entity.name} is {val}.")

        return " ".join(parts) if parts else None

    def answer_admission_query(self, question: str) -> Optional[str]:
        """Return admission portal information for India / International queries."""
        q = question.lower()
        if "international" in q:
            eid = "admission--international"
        elif any(w in q for w in ("india", "domestic", "admission", "admit")):
            eid = "admission--india"
        else:
            return None

        ent = self.entities.get(eid)
        if not ent:
            return None

        url_part = f" Visit: {ent.url}" if ent.url else ""
        return f"{ent.name} portal.{url_part}"

    # ----- serialization -----

    def save(self, path: str | Path) -> None:
        data = {
            "entities": {eid: e.to_dict() for eid, e in self.entities.items()},
            "relationships": [r.to_dict() for r in self.relationships],
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
        # Also save a JS version to bypass CORS for local visualization
        js_path = str(path).replace(".json", ".js")
        if js_path != str(path):
            with open(js_path, "w", encoding="utf-8") as f:
                f.write("window.knowledgeGraphData = ")
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write(";")

        log.info(
            f"KG saved: {len(self.entities)} entities, "
            f"{len(self.relationships)} relationships -> {path} (and .js)"
        )

    @classmethod
    def load(cls, path: str | Path) -> KnowledgeGraph:
        kg = cls()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for eid, edata in data["entities"].items():
            kg.add_entity(Entity.from_dict(edata))
        for rdata in data["relationships"]:
            kg.add_relationship(Relationship.from_dict(rdata))
        log.info(
            f"KG loaded: {len(kg.entities)} entities, "
            f"{len(kg.relationships)} relationships"
        )
        return kg

    def stats(self) -> dict:
        type_counts: dict[str, int] = {}
        for e in self.entities.values():
            type_counts[e.entity_type] = type_counts.get(e.entity_type, 0) + 1
        rel_counts: dict[str, int] = {}
        for r in self.relationships:
            rel_counts[r.relation_type] = rel_counts.get(r.relation_type, 0) + 1
        return {
            "total_entities": len(self.entities),
            "total_relationships": len(self.relationships),
            "entity_types": type_counts,
            "relationship_types": rel_counts,
        }


# ---------------------------------------------------------------------------
# Seed loader — always called first in build_knowledge_graph()
# ---------------------------------------------------------------------------

def _load_seeds(kg: KnowledgeGraph) -> None:
    """Populate the KG skeleton from hardcoded seed constants."""

    # 1. University root
    kg.add_entity(Entity(**SEED_UNIVERSITY))

    # 2. Campuses
    for c in SEED_CAMPUSES:
        kg.add_entity(Entity(entity_type="campus", attributes={}, **c))
        kg.add_relationship(Relationship(
            source_id="university--srmist",
            target_id=c["id"],
            relation_type="has_campus",
        ))

    # 3. KTR Colleges
    for col in SEED_KTR_COLLEGES:
        kg.add_entity(Entity(entity_type="college", campus="KTR", attributes={}, **col))
        kg.add_relationship(Relationship(
            source_id="campus--kattankulathur",
            target_id=col["id"],
            relation_type="has_college",
        ))

    # 4. Medicine sub-colleges
    for sc in SEED_MEDICINE_SUB_COLLEGES:
        kg.add_entity(Entity(
            entity_type="sub_college", campus="KTR",
            url="", attributes={}, **sc,
        ))
        kg.add_relationship(Relationship(
            source_id="college--medicine-and-health-sciences",
            target_id=sc["id"],
            relation_type="has_sub_college",
        ))

    # 5. FET Schools under Faculty of Engineering & Technology
    for school in SEED_FET_SCHOOLS:
        kg.add_entity(Entity(
            entity_type="school", campus="KTR",
            url="", attributes={}, **school,
        ))
        kg.add_relationship(Relationship(
            source_id=_FET,
            target_id=school["id"],
            relation_type="has_department",
        ))

    # 6. FET Centres
    for centre in SEED_FET_CENTRES:
        kg.add_entity(Entity(
            entity_type="centre", campus="KTR",
            url="", attributes={}, **centre,
        ))
        kg.add_relationship(Relationship(
            source_id=_FET,
            target_id=centre["id"],
            relation_type="has_centre",
        ))

    # 7. CSH Centres
    for centre in SEED_CSH_CENTRES:
        kg.add_entity(Entity(
            entity_type="centre", campus="KTR",
            url="", attributes={}, **centre,
        ))
        kg.add_relationship(Relationship(
            source_id=_CSH,
            target_id=centre["id"],
            relation_type="has_centre",
        ))

    # 8. KTR Directorates
    for d in SEED_KTR_DIRECTORATES:
        kg.add_entity(Entity(entity_type="directorate", campus="KTR", attributes={}, **d))
        kg.add_relationship(Relationship(
            source_id="campus--kattankulathur",
            target_id=d["id"],
            relation_type="has_directorate",
        ))

    # 9. KTR Facilities
    for fac in SEED_KTR_FACILITIES:
        kg.add_entity(Entity(entity_type="facility", campus="KTR", attributes={}, **fac))
        kg.add_relationship(Relationship(
            source_id="campus--kattankulathur",
            target_id=fac["id"],
            relation_type="has_facility",
        ))

    # 10. Admissions (under university)
    for adm in SEED_ADMISSIONS:
        kg.add_entity(Entity(entity_type="admission", campus="KTR", attributes={}, **adm))
        kg.add_relationship(Relationship(
            source_id="university--srmist",
            target_id=adm["id"],
            relation_type="has_admission",
        ))

    # 11. Publications
    for pub in SEED_PUBLICATIONS:
        kg.add_entity(Entity(entity_type="publication", campus="KTR", attributes={}, **pub))

    # 12. Misc pages
    for m in SEED_MISC:
        kg.add_entity(Entity(entity_type="misc", campus="KTR", attributes={}, **m))

    # 13. Cross-links
    for src, tgt, rel in SEED_CROSS_LINKS:
        if src in kg.entities and tgt in kg.entities:
            kg.add_relationship(Relationship(
                source_id=src, target_id=tgt, relation_type=rel,
            ))


# ---------------------------------------------------------------------------
# Builder: populate KG from scraped page data
# ---------------------------------------------------------------------------

# School names used in "Meet our Chairs" pages
_SCHOOL_NAMES = [
    "School of Computing",
    "School of Bio-Engineering",
    "School of Electrical and Electronics Engineering",
    "School of Mechanical Engineering",
    "School of Civil Engineering",
    "School of Architecture & Interior Design",
    "School of Basic Sciences",
    "School of BioEngineering",
]


def build_knowledge_graph(pages: list[dict]) -> KnowledgeGraph:
    """
    Build a KG from loaded page dicts.
    Each page dict: {"content": str, "meta": {...}, "table_text": str, "infobox_text": str}

    Seeds are loaded first so the institutional skeleton is always present.
    Scraped data is layered on top.
    """
    kg = KnowledgeGraph()

    # --- Seed the skeleton ---
    _load_seeds(kg)

    # --- Classify pages by URL pattern ---
    college_pages: dict[str, dict] = {}
    dept_pages: dict[str, dict] = {}
    program_pages: dict[str, dict] = {}
    centre_pages: dict[str, dict] = {}
    meet_pages: list[dict] = []

    for page in pages:
        url     = page["meta"].get("url", "")
        title   = page["meta"].get("title", "")
        content = page["content"]
        campus  = _detect_campus(url, content)

        # ---- College root ----
        m = _COLLEGE_ROOT_RE.match(url)
        if m:
            slug = m.group(1)
            # Resolve scraped slug to canonical seed ID if known
            eid = _COLLEGE_URL_SLUG_TO_SEED.get(slug, f"college--{slug}")
            # Merge scraped info into seed (or create new entry)
            if eid not in kg.entities:
                name = _derive_college_name(title, slug)
                kg.add_entity(Entity(
                    id=eid, name=name, entity_type="college",
                    campus=campus, url=url, attributes={},
                ))
                kg.add_relationship(Relationship(
                    source_id=f"campus--{campus.lower()}",
                    target_id=eid,
                    relation_type="has_college",
                ))
            else:
                # Update URL on existing seed entity
                kg.entities[eid].url = url
            college_pages[slug] = page
            continue

        # ---- Department sub-page (centres under departments) ----
        m = _DEPT_SUBPAGE_RE.match(url)
        if m:
            dept_slug = m.group(1)
            sub_slug  = m.group(2)
            # If it looks like a centre page, create/link as centre
            if _is_centre_slug(sub_slug):
                centre_eid = f"centre--{sub_slug}"
                dept_eid   = f"department--{dept_slug}"
                display_name = title.split("|")[0].replace(" - SRMIST", "").strip()
                if not display_name or len(display_name) < 3:
                    display_name = sub_slug.replace("-", " ").title()
                if centre_eid not in kg.entities:
                    kg.add_entity(Entity(
                        id=centre_eid, name=display_name, entity_type="centre",
                        campus=campus, url=url, attributes={},
                    ))
                else:
                    kg.entities[centre_eid].url = url
                # Link to parent department
                if dept_eid in kg.entities:
                    kg.add_relationship(Relationship(
                        source_id=dept_eid, target_id=centre_eid,
                        relation_type="has_centre",
                    ))
                centre_pages[sub_slug] = page
            continue

        # ---- Department root ----
        m = _DEPT_ROOT_RE.match(url)
        if m:
            slug = m.group(1)

            # Skip blocklisted slugs (garbage, sub-college dupes, CDC pages)
            if slug in _DEPT_SLUG_BLOCKLIST:
                log.debug(f"Skipping blocklisted department slug: {slug}")
                continue

            # Skip slugs that should be merged/dropped
            if slug in _DEPT_SLUG_MERGE:
                merge_target = _DEPT_SLUG_MERGE[slug]
                if merge_target and merge_target in kg.entities:
                    # Update the merge target's URL if needed
                    kg.entities[merge_target].url = url
                log.debug(f"Skipping duplicate department slug: {slug}")
                continue

            # Detect centres masquerading as departments
            if _is_centre_slug(slug):
                centre_eid = f"centre--{slug}"
                display_name = title.split("|")[0].replace(" - SRMIST", "").strip()
                if not display_name or len(display_name) < 3:
                    display_name = slug.replace("-", " ").title()
                if centre_eid not in kg.entities:
                    kg.add_entity(Entity(
                        id=centre_eid, name=display_name, entity_type="centre",
                        campus=campus, url=url, attributes={},
                    ))
                else:
                    kg.entities[centre_eid].url = url
                centre_pages[slug] = page
                continue

            eid  = f"department--{slug}"
            raw_name = slug.replace("department-of-", "").replace("-", " ").strip().title()
            display_name = title.split("|")[0].replace(" - SRMIST", "").strip()
            if display_name.startswith("Department of"):
                raw_name = display_name.replace("Department of ", "").strip()
            elif "Department of" in display_name:
                raw_name = display_name

            attrs: dict = {}
            hod_match = _HOD_PATTERN.search(content[:3000])
            if hod_match:
                attrs["hod"] = hod_match.group(1).strip().rstrip(".")
            dean_match = _DEAN_PATTERN.search(content[:3000])
            if dean_match:
                attrs["dean"] = dean_match.group(1).strip().rstrip(".")

            if eid not in kg.entities:
                kg.add_entity(Entity(
                    id=eid, name=raw_name, entity_type="department",
                    campus=campus, url=url, attributes=attrs,
                ))
            else:
                kg.entities[eid].url = url
                kg.entities[eid].attributes.update(attrs)

            # --- Assign to correct college based on seed data ---
            if slug in _FET_DEPT_SLUGS:
                # Find which school this dept belongs to and link
                for school_id, dept_slugs in SEED_FET_SCHOOL_DEPTS.items():
                    if slug in dept_slugs:
                        kg.add_relationship(Relationship(
                            source_id=school_id, target_id=eid,
                            relation_type="has_department",
                        ))
                        break
            elif slug in _CSH_DEPT_SLUGS:
                kg.add_relationship(Relationship(
                    source_id=_CSH, target_id=eid,
                    relation_type="has_department",
                ))

            dept_pages[slug] = page
            continue

        # ---- Program ----
        m = _PROGRAM_RE.match(url)
        if m:
            slug = m.group(1)
            eid  = f"program--{slug}"
            display_name = title.split("|")[0].replace(" - SRMIST", "").strip()
            if not display_name or len(display_name) < 3:
                display_name = slug.replace("-", " ").title()

            attrs = {}
            # Extract fees / eligibility / criteria from infobox / table text if present
            infobox = page.get("infobox_text", "") or ""
            table   = page.get("table_text", "") or ""
            combined_extra = f"{infobox} {table}"
            fee_m = re.search(r"(?:fee|fees|tuition)[^\d]*(\d[\d,./\- ]+)", combined_extra, re.I)
            if fee_m:
                attrs["fees"] = fee_m.group(1).strip()
            elig_m = re.search(r"(?:eligibility|criteria)[:\s]+([^\n]{5,200})", combined_extra, re.I)
            if elig_m:
                attrs["eligibility"] = elig_m.group(1).strip()

            if eid not in kg.entities:
                kg.add_entity(Entity(
                    id=eid, name=display_name, entity_type="program",
                    campus=campus, url=url, attributes=attrs,
                ))
            else:
                kg.entities[eid].attributes.update(attrs)
            program_pages[slug] = page
            continue

        # ---- Centre (/centre/ or /center/ URLs) ----
        m = _CENTRE_RE.match(url)
        if m:
            slug = m.group(1)
            eid  = f"centre--{slug}"
            display_name = title.split("|")[0].replace(" - SRMIST", "").strip()
            if not display_name or len(display_name) < 3:
                display_name = slug.replace("-", " ").title()
            if eid not in kg.entities:
                kg.add_entity(Entity(
                    id=eid, name=display_name, entity_type="centre",
                    campus=campus, url=url, attributes={},
                ))
            else:
                kg.entities[eid].url = url
            centre_pages[slug] = page
            continue

        # ---- Lab pages (/lab/ URLs — often department-linked centres) ----
        m = _LAB_RE.match(url)
        if m:
            slug = m.group(1)
            eid  = f"centre--{slug}"
            display_name = title.split("|")[0].replace(" - SRMIST", "").strip()
            if not display_name or len(display_name) < 3:
                display_name = slug.replace("-", " ").title()
            if eid not in kg.entities:
                kg.add_entity(Entity(
                    id=eid, name=display_name, entity_type="centre",
                    campus=campus, url=url, attributes={},
                ))
            else:
                kg.entities[eid].url = url
            centre_pages[slug] = page
            continue

        # ---- Admission pages ----
        m = _ADMISSION_RE.match(url)
        if m:
            kind = m.group(1).lower()  # "india" or "international"
            eid  = f"admission--{kind}"
            if eid in kg.entities:
                kg.entities[eid].url = url
            continue

        # ---- Publication / faculty gateway ----
        if _PUBLICATION_RE.search(url):
            # already seeded; just update URL
            for pub_eid in ("publication--publications", "publication--faculty-achievements"):
                if pub_eid in kg.entities and kg.entities[pub_eid].url in ("", url):
                    kg.entities[pub_eid].url = url
            continue

        # ---- Meet our Chairs pages ----
        if "meet-our-chairs" in url.lower() or "meet-our-chairs-deans-and-hods" in url.lower():
            meet_pages.append(page)
            continue

    # --- Parse "Meet our Chairs, Deans & HoDs" pages ---
    for page in meet_pages:
        content = page["content"]
        url     = page["meta"].get("url", "")

        for match in _MEET_HOD_PATTERN.finditer(content):
            person_name = match.group(1).strip().rstrip(".")
            dept_name   = match.group(2).strip().rstrip(".")
            best_dept   = _find_department_entity(kg, dept_name)
            if best_dept:
                best_dept.attributes["hod"] = person_name
            else:
                log.debug(f"Could not match HOD department: {dept_name!r} for {person_name}")

        for match in _MEET_CHAIR_PATTERN.finditer(content):
            person_name = match.group(1).strip().rstrip(".")
            school_name = match.group(2).strip().rstrip(".")
            best_school = _find_school_entity(kg, school_name)
            if best_school:
                best_school.attributes["chairperson"] = person_name

    # --- Infer dept / programme relationships from internal_links ---
    for page in pages:
        url            = page["meta"].get("url", "")
        internal_links = page["meta"].get("internal_links", [])

        m_college = _COLLEGE_ROOT_RE.match(url)
        if m_college:
            college_slug = m_college.group(1)
            # Resolve to canonical seed ID
            college_eid = _COLLEGE_URL_SLUG_TO_SEED.get(college_slug, f"college--{college_slug}")
            for link in internal_links:
                _maybe_link_dept(kg, college_eid, link, "has_department")
                _maybe_link_prog(kg, college_eid, link, "offers_program")
                _maybe_link_centre(kg, college_eid, link)

        m_dept_root = _DEPT_ROOT_RE.match(url)
        if m_dept_root:
            dept_slug = m_dept_root.group(1)
            dept_eid  = f"department--{dept_slug}"
            if dept_eid in kg.entities:
                for link in internal_links:
                    _maybe_link_prog(kg, dept_eid, link, "offers_program")
                    _maybe_link_centre(kg, dept_eid, link)

    # --- Infer school groupings from "Meet our Chairs" pages ---
    _infer_school_groupings(kg, meet_pages)

    # --- Enforce single-parent for departments and programs ---
    _enforce_single_parent(kg)

    # --- Deduplicate relationships ---
    _deduplicate_relationships(kg)

    log.info(f"KG built: {kg.stats()}")
    return kg


# ---------------------------------------------------------------------------
# Link-inference helpers
# ---------------------------------------------------------------------------

def _maybe_link_dept(kg: KnowledgeGraph, source_eid: str, link: str, rel: str) -> None:
    m = _DEPT_ROOT_RE.match(link.rstrip("/") + "/")
    if m:
        dept_eid = f"department--{m.group(1)}"
        if dept_eid in kg.entities:
            kg.add_relationship(Relationship(
                source_id=source_eid, target_id=dept_eid, relation_type=rel,
            ))


def _maybe_link_prog(kg: KnowledgeGraph, source_eid: str, link: str, rel: str) -> None:
    m = _PROGRAM_RE.match(link.rstrip("/") + "/")
    if m:
        prog_eid = f"program--{m.group(1)}"
        if prog_eid in kg.entities:
            kg.add_relationship(Relationship(
                source_id=source_eid, target_id=prog_eid, relation_type=rel,
            ))


def _maybe_link_centre(kg: KnowledgeGraph, source_eid: str, link: str) -> None:
    m = _CENTRE_RE.match(link)
    if m:
        centre_eid = f"centre--{m.group(1)}"
        if centre_eid in kg.entities:
            kg.add_relationship(Relationship(
                source_id=source_eid, target_id=centre_eid, relation_type="has_centre",
            ))
            # Also link to Directorate of Research
            if "directorate--directorate-of-research" in kg.entities:
                kg.add_relationship(Relationship(
                    source_id="directorate--directorate-of-research",
                    target_id=centre_eid,
                    relation_type="has_centre",
                ))


def _deduplicate_relationships(kg: KnowledgeGraph) -> None:
    seen_rels: set[tuple[str, str, str]] = set()
    unique_rels: list[Relationship] = []
    for r in kg.relationships:
        key = (r.source_id, r.target_id, r.relation_type)
        if key not in seen_rels:
            seen_rels.add(key)
            unique_rels.append(r)
    kg.relationships = unique_rels
    kg._children_idx.clear()
    kg._parent_idx.clear()
    _parent_rel_types = {
        "has_campus", "has_college", "has_sub_college",
        "has_department", "has_centre", "has_directorate",
        "has_facility", "belongs_to",
    }
    for r in unique_rels:
        kg._children_idx.setdefault(r.source_id, []).append(r.target_id)
        if r.relation_type in _parent_rel_types:
            kg._parent_idx[r.target_id] = r.source_id


def _derive_college_name(title: str, slug: str) -> str:
    if "engineering" in title.lower() and "technology" in title.lower():
        return "Faculty of Engineering & Technology"
    if "science" in title.lower() and "humanities" in title.lower():
        return "Faculty of Science & Humanities"
    if "management" in title.lower():
        return "Faculty of Management"
    if "law" in title.lower():
        return "SRM School of Law"
    if "agriculture" in title.lower() or "agricultural" in title.lower():
        return "College of Agricultural Sciences"
    if "medicine" in title.lower() or "health" in title.lower():
        return "Medicine & Health Sciences"
    return title.replace(" - SRMIST", "").replace("Welcome to ", "").strip()


# ---------------------------------------------------------------------------
# School / department fuzzy-match helpers
# ---------------------------------------------------------------------------

def _find_department_entity(kg: KnowledgeGraph, name: str) -> Optional[Entity]:
    """Fuzzy match a department name to an existing KG entity."""
    name_lower = name.lower().strip()

    for ent in kg.entities.values():
        if ent.entity_type not in ("department", "sub_college"):
            continue
        if ent.name.lower() == name_lower:
            return ent
        if name_lower in ent.name.lower() or ent.name.lower() in name_lower:
            return ent

    tokens = set(name_lower.split())
    best_match: Optional[Entity] = None
    best_overlap = 0
    for ent in kg.entities.values():
        if ent.entity_type not in ("department", "sub_college"):
            continue
        ent_tokens = set(ent.name.lower().split())
        overlap = len(tokens & ent_tokens)
        if overlap > best_overlap and overlap >= max(1, len(tokens) - 1):
            best_overlap = overlap
            best_match = ent

    return best_match


def _find_school_entity(kg: KnowledgeGraph, name: str) -> Optional[Entity]:
    """Fuzzy match a school/college name to an existing KG entity."""
    name_lower = name.lower().strip()
    for ent in kg.entities.values():
        if ent.entity_type not in ("school", "college", "sub_college"):
            continue
        if ent.name.lower() == name_lower:
            return ent
        if name_lower in ent.name.lower() or ent.name.lower() in name_lower:
            return ent
    return None


# ---------------------------------------------------------------------------
# School-grouping inference from "Meet our Chairs" pages
# ---------------------------------------------------------------------------

def _infer_school_groupings(kg: KnowledgeGraph, meet_pages: list[dict]) -> None:
    """Parse 'Meet our Chairs' pages to create School entities and link departments."""
    for page in meet_pages:
        content = page["content"]
        url     = page["meta"].get("url", "")
        campus  = _detect_campus(url, content)

        parent_college_slug = None
        m = _COLLEGE_SUBPAGE_RE.match(url)
        if m:
            parent_college_slug = m.group(1)

        full_text = " ".join(content.split("\n"))

        for school_name in _SCHOOL_NAMES:
            if school_name.lower() not in full_text.lower():
                continue

            school_slug = school_name.lower().replace(" ", "-").replace("&", "and")
            school_eid  = f"school--{school_slug}"
            if school_eid not in kg.entities:
                kg.add_entity(Entity(
                    id=school_eid, name=school_name, entity_type="school",
                    campus=campus, url="", attributes={},
                ))

            if parent_college_slug:
                college_eid = f"college--{parent_college_slug}"
                if college_eid in kg.entities:
                    kg.add_relationship(Relationship(
                        source_id=college_eid, target_id=school_eid,
                        relation_type="has_department",
                    ))

        _parse_school_dept_blocks(kg, full_text, campus)


def _parse_school_dept_blocks(kg: KnowledgeGraph, text: str, campus: str) -> None:
    """Parse structured blocks like 'School of Computing ... Dr X Head ...'."""
    school_re = re.compile(
        r"(School\s+of\s+[A-Za-z &\-]+?)(?=\s+Dr\.|\s+Prof\.|\s+School\s+of|\s+Department\s+of|$)",
        re.I,
    )
    head_re = re.compile(
        r"(?:Dr\.?\s*|Prof\.?\s*)([A-Z][A-Za-z.\-' ]+?)\s+"
        r"(?:Professor\s*&?\s*|Associate\s+Professor\s*&?\s*|Research\s+(?:Professor|Associate\s+Professor)\s*&?\s*)?"
        r"Head\s+"
        r"([A-Za-z &,.\-]+?)(?=\s+Dr\.|\s+Prof\.|\s+School|\s+Pioneering|\s+Department|$)",
        re.I,
    )
    chair_re = re.compile(
        r"(?:Dr\.?\s*|Prof\.?\s*)([A-Z][A-Za-z.\-' ]+?)\s+"
        r"(?:Professor\s*&?\s*|Associate\s+Professor\s*&?\s*)?"
        r"Chairperson\s+"
        r"([A-Za-z &,.\-]+?)(?=\s+Dr\.|\s+Prof\.|\s+School|\s+Pioneering|\s+Department|$)",
        re.I,
    )

    school_positions = []
    for m in school_re.finditer(text):
        school_positions.append((m.start(), m.group(1).strip()))

    for i, (pos, school_name) in enumerate(school_positions):
        end_pos = school_positions[i + 1][0] if i + 1 < len(school_positions) else len(text)
        block = text[pos:end_pos]

        school_slug = school_name.lower().replace(" ", "-").replace("&", "and")
        school_eid  = f"school--{school_slug}"

        if school_eid not in kg.entities:
            kg.add_entity(Entity(
                id=school_eid, name=school_name, entity_type="school",
                campus=campus, url="", attributes={},
            ))

        for cm in chair_re.finditer(block):
            person = cm.group(1).strip().rstrip(".")
            kg.entities[school_eid].attributes["chairperson"] = person

        for hm in head_re.finditer(block):
            person       = hm.group(1).strip().rstrip(".")
            dept_name_raw = hm.group(2).strip().rstrip(".")

            dept_entity = _find_department_entity(kg, dept_name_raw)
            if dept_entity:
                dept_entity.attributes["hod"] = person
                kg.add_relationship(Relationship(
                    source_id=school_eid, target_id=dept_entity.id,
                    relation_type="has_department",
                ))
            else:
                dept_slug = dept_name_raw.lower().replace(" ", "-").replace("&", "and")
                dept_eid  = f"department--department-of-{dept_slug}"
                if dept_eid not in kg.entities:
                    kg.add_entity(Entity(
                        id=dept_eid, name=dept_name_raw.title(),
                        entity_type="department", campus=campus,
                        url="", attributes={"hod": person},
                    ))
                else:
                    kg.entities[dept_eid].attributes["hod"] = person

                kg.add_relationship(Relationship(
                    source_id=school_eid, target_id=dept_eid,
                    relation_type="has_department",
                ))
