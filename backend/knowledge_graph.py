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
    has_admission_child | admission_covers | admission_governs |
    collaborates_with | also_listed_under | belongs_to

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

import csv as _csv

from backend.admission_profiles import (
    integrate_admissions,
    _normalize_program_text,
    _program_tokens,
    _token_overlap,
)

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
    {
        "id": "sub_college--college-of-medicine",
        "name": "SRM Medical College Hospital and Research Centre (SRM MCHRC)",
        "url": "https://medical.srmist.edu.in/",
    },
    {
        "id": "sub_college--college-of-dentistry",
        "name": "SRM Kattankulathur Dental College",
        "url": "https://dental.srmist.edu.in/",
    },
    {
        "id": "sub_college--college-of-pharmacy",
        "name": "College of Pharmacy",
        "url": "https://www.srmist.edu.in/department/college-of-pharmacy/",
    },
    {
        "id": "sub_college--college-of-physiotherapy",
        "name": "College of Physiotherapy",
        "url": "https://www.srmist.edu.in/department/college-of-physiotherapy/",
    },
    {
        "id": "sub_college--college-of-occupational-therapy",
        "name": "College of Occupational Therapy",
        "url": "https://www.srmist.edu.in/department/college-of-occupational-therapy/",
    },
    {
        "id": "sub_college--college-of-nursing",
        "name": "College of Nursing",
        "url": "https://www.srmist.edu.in/department/college-of-nursing/",
    },
    {
        "id": "sub_college--school-of-public-health",
        "name": "School of Public Health",
        "url": "https://www.srmist.edu.in/srm-school-of-public-health/",
    },
]

# Departments under Medicine & Health Sciences. The medical and dental sites
# live on dedicated subdomains and are not fully captured by the main-site URL
# patterns, so the stable department hierarchy is seeded explicitly here.
SEED_MEDICINE_DEPARTMENTS = [
    {
        "id": "department--medical-anatomy",
        "name": "Anatomy",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/anatomy/",
        "attributes": {"category": "pre-and-para-clinical"},
    },
    {
        "id": "department--medical-physiology",
        "name": "Physiology",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/physiology/",
        "attributes": {"category": "pre-and-para-clinical"},
    },
    {
        "id": "department--medical-biochemistry",
        "name": "Biochemistry",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/biochemistry/",
        "attributes": {"category": "pre-and-para-clinical"},
    },
    {
        "id": "department--medical-pharmacology",
        "name": "Pharmacology",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/pharmacology/",
        "attributes": {"category": "pre-and-para-clinical"},
    },
    {
        "id": "department--medical-pathology",
        "name": "Pathology",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/pathology/",
        "attributes": {"category": "pre-and-para-clinical"},
    },
    {
        "id": "department--medical-microbiology",
        "name": "Microbiology",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/microbiology/",
        "attributes": {"category": "pre-and-para-clinical"},
    },
    {
        "id": "department--medical-forensic-medicine",
        "name": "Forensic Medicine",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/forensic-medicine/",
        "attributes": {"category": "pre-and-para-clinical"},
    },
    {
        "id": "department--medical-community-medicine",
        "name": "Community Medicine",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/community-medicine/",
        "attributes": {"category": "pre-and-para-clinical"},
    },
    {
        "id": "department--medical-general-medicine",
        "name": "General Medicine",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/general-medicine/",
        "attributes": {"category": "clinical"},
    },
    {
        "id": "department--medical-paediatrics",
        "name": "Paediatrics",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/paediatrics/",
        "attributes": {"category": "clinical"},
    },
    {
        "id": "department--medical-psychiatry",
        "name": "Psychiatry",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/psychiatry/",
        "attributes": {"category": "clinical"},
    },
    {
        "id": "department--medical-dermatology",
        "name": "Dermatology",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/dermatology/",
        "attributes": {"category": "clinical"},
    },
    {
        "id": "department--medical-respiratory-medicine",
        "name": "Respiratory Medicine",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/respiratory-medicine/",
        "attributes": {"category": "clinical"},
    },
    {
        "id": "department--medical-general-surgery",
        "name": "General Surgery",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/general-surgery/",
        "attributes": {"category": "clinical"},
    },
    {
        "id": "department--medical-orthopaedics",
        "name": "Orthopaedics",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/orthopaedics/",
        "attributes": {"category": "clinical"},
    },
    {
        "id": "department--medical-ent",
        "name": "Otorhinolaryngology (ENT)",
        "parent_id": "sub_college--college-of-medicine",
        "attributes": {"category": "clinical"},
    },
    {
        "id": "department--medical-ophthalmology",
        "name": "Ophthalmology",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/ophthalmology/",
        "attributes": {"category": "clinical"},
    },
    {
        "id": "department--medical-obstetrics-and-gynaecology",
        "name": "Obstetrics and Gynaecology",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/obstetrics-and-gynaecology/",
        "attributes": {"category": "clinical"},
    },
    {
        "id": "department--medical-anaesthesiology",
        "name": "Anaesthesiology",
        "parent_id": "sub_college--college-of-medicine",
        "attributes": {"category": "clinical"},
    },
    {
        "id": "department--medical-radiology",
        "name": "Radiology",
        "parent_id": "sub_college--college-of-medicine",
        "attributes": {"category": "clinical"},
    },
    {
        "id": "department--medical-emergency-medicine",
        "name": "Emergency Medicine",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/emergency-medicines/",
        "attributes": {"category": "clinical"},
    },
    {
        "id": "department--medical-transfusion-medicine",
        "name": "Transfusion Medicine and Blood Centre",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/transfusion-medicine-and-blood-centre/",
        "attributes": {"category": "clinical"},
    },
    {
        "id": "department--medical-critical-care-medicine",
        "name": "Critical Care Medicine",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/critical-care-medicine/",
        "attributes": {"category": "super-speciality"},
    },
    {
        "id": "department--medical-cardiology",
        "name": "Cardiology",
        "parent_id": "sub_college--college-of-medicine",
        "attributes": {"category": "super-speciality"},
    },
    {
        "id": "department--medical-cardiovascular-and-thoracic-surgery",
        "name": "Cardiovascular and Thoracic Surgery",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/cardio-thoracic-vascular-surgery/",
        "attributes": {"category": "super-speciality"},
    },
    {
        "id": "department--medical-nephrology",
        "name": "Nephrology",
        "parent_id": "sub_college--college-of-medicine",
        "attributes": {"category": "super-speciality"},
    },
    {
        "id": "department--medical-urology",
        "name": "Urology",
        "parent_id": "sub_college--college-of-medicine",
        "attributes": {"category": "super-speciality"},
    },
    {
        "id": "department--medical-neurology",
        "name": "Neurology",
        "parent_id": "sub_college--college-of-medicine",
        "attributes": {"category": "super-speciality"},
    },
    {
        "id": "department--medical-neurosurgery",
        "name": "Neurosurgery",
        "parent_id": "sub_college--college-of-medicine",
        "attributes": {"category": "super-speciality"},
    },
    {
        "id": "department--medical-plastic-and-reconstructive-surgery",
        "name": "Plastic and Reconstructive Surgery",
        "parent_id": "sub_college--college-of-medicine",
        "attributes": {"category": "super-speciality"},
    },
    {
        "id": "department--medical-paediatric-surgery",
        "name": "Paediatric Surgery",
        "parent_id": "sub_college--college-of-medicine",
        "attributes": {"category": "super-speciality"},
    },
    {
        "id": "department--medical-medical-gastroenterology",
        "name": "Medical Gastroenterology",
        "parent_id": "sub_college--college-of-medicine",
        "attributes": {"category": "super-speciality"},
    },
    {
        "id": "department--medical-surgical-gastroenterology",
        "name": "Surgical Gastroenterology",
        "parent_id": "sub_college--college-of-medicine",
        "attributes": {"category": "super-speciality"},
    },
    {
        "id": "department--medical-medical-oncology",
        "name": "Medical Oncology",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/medical-oncology/",
        "attributes": {"category": "super-speciality"},
    },
    {
        "id": "department--medical-surgical-oncology",
        "name": "Surgical Oncology",
        "parent_id": "sub_college--college-of-medicine",
        "attributes": {"category": "super-speciality"},
    },
    {
        "id": "department--medical-vascular-surgery",
        "name": "Vascular Surgery",
        "parent_id": "sub_college--college-of-medicine",
        "attributes": {"category": "super-speciality"},
    },
    {
        "id": "department--medical-endocrinology",
        "name": "Endocrinology",
        "parent_id": "sub_college--college-of-medicine",
        "attributes": {"category": "super-speciality"},
    },
    {
        "id": "department--medical-rheumatology",
        "name": "Rheumatology",
        "parent_id": "sub_college--college-of-medicine",
        "attributes": {"category": "super-speciality"},
    },
    {
        "id": "department--allied-health-sciences",
        "name": "Allied Health Sciences",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/allied-health-science-departments/",
        "attributes": {"category": "academic-unit"},
    },
    {
        "id": "department--allied-health-optometry",
        "name": "Optometry",
        "parent_id": "department--allied-health-sciences",
        "url": "https://medical.srmist.edu.in/departments/optometry/",
        "attributes": {"category": "allied-health"},
    },
    {
        "id": "department--allied-health-clinical-psychology",
        "name": "Clinical Psychology",
        "parent_id": "department--allied-health-sciences",
        "url": "https://medical.srmist.edu.in/departments/clinical-psychology/",
        "attributes": {"category": "allied-health"},
    },
    {
        "id": "department--allied-health-audiology-and-speech-language-pathology",
        "name": "Audiology and Speech-Language Pathology",
        "parent_id": "department--allied-health-sciences",
        "url": "https://medical.srmist.edu.in/departments/audiology-and-speech-language-pathology/",
        "attributes": {"category": "allied-health"},
    },
    {
        "id": "department--allied-health-clinical-nutrition-and-dietetics",
        "name": "Clinical Nutrition and Dietetics",
        "parent_id": "department--allied-health-sciences",
        "url": "https://medical.srmist.edu.in/departments/clinical-nutrition-and-dietetics/",
        "attributes": {"category": "allied-health"},
    },
]

SEED_MEDICINE_DEPARTMENTS += [
    {
        "id": "department--dental-oral-and-maxillofacial-surgery",
        "name": "Oral & Maxillofacial Surgery",
        "parent_id": "sub_college--college-of-dentistry",
        "url": "https://dental.srmist.edu.in/dental-departments/",
    },
    {
        "id": "department--dental-oral-and-maxillofacial-pathology",
        "name": "Oral and Maxillofacial Pathology",
        "parent_id": "sub_college--college-of-dentistry",
        "url": "https://dental.srmist.edu.in/dental-departments/",
    },
    {
        "id": "department--dental-prosthodontics-and-crown-and-bridge",
        "name": "Prosthodontics and Crown & Bridge",
        "parent_id": "sub_college--college-of-dentistry",
        "url": "https://dental.srmist.edu.in/dental-departments/",
    },
    {
        "id": "department--dental-periodontology",
        "name": "Periodontology",
        "parent_id": "sub_college--college-of-dentistry",
        "url": "https://dental.srmist.edu.in/dental-departments/",
    },
    {
        "id": "department--dental-orthodontics-and-dentofacial-orthopedics",
        "name": "Orthodontics & Dentofacial Orthopedics",
        "parent_id": "sub_college--college-of-dentistry",
        "url": "https://dental.srmist.edu.in/dental-departments/",
    },
    {
        "id": "department--dental-conservative-dentistry-and-endodontics",
        "name": "Conservative Dentistry and Endodontics",
        "parent_id": "sub_college--college-of-dentistry",
        "url": "https://dental.srmist.edu.in/dental-departments/",
    },
    {
        "id": "department--dental-pediatric-and-preventive-dentistry",
        "name": "Pediatric and Preventive Dentistry",
        "parent_id": "sub_college--college-of-dentistry",
        "url": "https://dental.srmist.edu.in/dental-departments/",
    },
    {
        "id": "department--dental-public-health-dentistry",
        "name": "Public Health Dentistry",
        "parent_id": "sub_college--college-of-dentistry",
        "url": "https://dental.srmist.edu.in/dental-departments/",
    },
    {
        "id": "department--dental-oral-medicine-and-radiology",
        "name": "Oral Medicine and Radiology",
        "parent_id": "sub_college--college-of-dentistry",
        "url": "https://dental.srmist.edu.in/dental-departments/",
    },
    {
        "id": "department--pharmacy-pharmaceutics",
        "name": "Pharmaceutics",
        "parent_id": "sub_college--college-of-pharmacy",
    },
    {
        "id": "department--pharmacy-pharmaceutical-analysis",
        "name": "Pharmaceutical Analysis",
        "parent_id": "sub_college--college-of-pharmacy",
    },
    {
        "id": "department--pharmacy-pharmaceutical-chemistry",
        "name": "Pharmaceutical Chemistry",
        "parent_id": "sub_college--college-of-pharmacy",
    },
    {
        "id": "department--pharmacy-pharmacology",
        "name": "Pharmacology",
        "parent_id": "sub_college--college-of-pharmacy",
    },
    {
        "id": "department--pharmacy-pharmacognosy",
        "name": "Pharmacognosy",
        "parent_id": "sub_college--college-of-pharmacy",
    },
    {
        "id": "department--pharmacy-pharmacy-practice",
        "name": "Pharmacy Practice",
        "parent_id": "sub_college--college-of-pharmacy",
    },
    {
        "id": "department--physiotherapy-orthopaedics",
        "name": "Orthopaedics",
        "parent_id": "sub_college--college-of-physiotherapy",
    },
    {
        "id": "department--physiotherapy-neurology",
        "name": "Neurology",
        "parent_id": "sub_college--college-of-physiotherapy",
    },
    {
        "id": "department--physiotherapy-cardio-pulmonary-sciences",
        "name": "Cardio-Pulmonary Sciences",
        "parent_id": "sub_college--college-of-physiotherapy",
    },
    {
        "id": "department--physiotherapy-sports-physiotherapy",
        "name": "Sports Physiotherapy",
        "parent_id": "sub_college--college-of-physiotherapy",
    },
    {
        "id": "department--physiotherapy-paediatrics",
        "name": "Paediatrics",
        "parent_id": "sub_college--college-of-physiotherapy",
    },
]

SEED_MEDICINE_DEPARTMENTS += [
    {
        "id": "department--nursing-medical-surgical-nursing",
        "name": "Medical Surgical Nursing",
        "parent_id": "sub_college--college-of-nursing",
    },
    {
        "id": "department--nursing-community-health-nursing",
        "name": "Community Health Nursing",
        "parent_id": "sub_college--college-of-nursing",
    },
    {
        "id": "department--nursing-obstetrics-and-gynaecology-nursing",
        "name": "Obstetrics and Gynaecology Nursing",
        "parent_id": "sub_college--college-of-nursing",
    },
    {
        "id": "department--nursing-paediatric-nursing",
        "name": "Paediatric Nursing",
        "parent_id": "sub_college--college-of-nursing",
    },
    {
        "id": "department--nursing-psychiatric-nursing",
        "name": "Psychiatric Nursing",
        "parent_id": "sub_college--college-of-nursing",
    },
    {
        "id": "department--occupational-therapy-neurosciences",
        "name": "Neurosciences",
        "parent_id": "sub_college--college-of-occupational-therapy",
    },
    {
        "id": "department--occupational-therapy-paediatrics",
        "name": "Paediatrics",
        "parent_id": "sub_college--college-of-occupational-therapy",
    },
    {
        "id": "department--occupational-therapy-hand-rehabilitation",
        "name": "Hand Rehabilitation",
        "parent_id": "sub_college--college-of-occupational-therapy",
    },
    {
        "id": "department--occupational-therapy-mental-health",
        "name": "Mental Health",
        "parent_id": "sub_college--college-of-occupational-therapy",
    },
    {
        "id": "department--occupational-therapy-sensory-integration",
        "name": "Sensory Integration",
        "parent_id": "sub_college--college-of-occupational-therapy",
    },
    {
        "id": "department--public-health-general",
        "name": "Public Health",
        "parent_id": "sub_college--school-of-public-health",
    },
    {
        "id": "department--public-health-biostatistics-and-epidemiology",
        "name": "Biostatistics and Epidemiology",
        "parent_id": "sub_college--school-of-public-health",
    },
    {
        "id": "department--public-health-health-data-science",
        "name": "Health Data Science",
        "parent_id": "sub_college--school-of-public-health",
    },
]

# Only Medicine, Dentistry, and Pharmacy maintain true department lists under
# Medicine & Health Sciences. The remaining sub-colleges are modeled as
# college-cum-department units, so their programs and centres attach directly
# to the sub_college node rather than to synthetic child departments.
_COLLAPSED_MEDICINE_SUB_COLLEGE_DEPARTMENT_IDS = {
    "department--physiotherapy-orthopaedics",
    "department--physiotherapy-neurology",
    "department--physiotherapy-cardio-pulmonary-sciences",
    "department--physiotherapy-sports-physiotherapy",
    "department--physiotherapy-paediatrics",
    "department--nursing-medical-surgical-nursing",
    "department--nursing-community-health-nursing",
    "department--nursing-obstetrics-and-gynaecology-nursing",
    "department--nursing-paediatric-nursing",
    "department--nursing-psychiatric-nursing",
    "department--occupational-therapy-neurosciences",
    "department--occupational-therapy-paediatrics",
    "department--occupational-therapy-hand-rehabilitation",
    "department--occupational-therapy-mental-health",
    "department--occupational-therapy-sensory-integration",
    "department--public-health-general",
    "department--public-health-biostatistics-and-epidemiology",
    "department--public-health-health-data-science",
}
_REPLACED_MEDICINE_DEPARTMENT_IDS = {
    "department--medical-anaesthesiology",
    "department--medical-radiology",
    "department--medical-cardiovascular-and-thoracic-surgery",
    "department--medical-endocrinology",
    "department--medical-surgical-oncology",
    "department--medical-vascular-surgery",
    "department--allied-health-sciences",
    "department--allied-health-optometry",
    "department--allied-health-clinical-psychology",
    "department--allied-health-audiology-and-speech-language-pathology",
    "department--allied-health-clinical-nutrition-and-dietetics",
}
SEED_MEDICINE_DEPARTMENTS = [
    dept for dept in SEED_MEDICINE_DEPARTMENTS
    if dept["id"] not in _COLLAPSED_MEDICINE_SUB_COLLEGE_DEPARTMENT_IDS
    and dept["id"] not in _REPLACED_MEDICINE_DEPARTMENT_IDS
]

SEED_MEDICINE_DEPARTMENTS += [
    {
        "id": "department--medical-anaesthesia",
        "name": "Anaesthesia",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/anaesthesia/",
        "attributes": {"category": "clinical"},
    },
    {
        "id": "department--medical-radio-diagnosis",
        "name": "Radio Diagnosis",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/radio-diagnosis/",
        "attributes": {"category": "clinical"},
    },
    {
        "id": "department--medical-physical-medicine-and-rehabilitation",
        "name": "Physical Medicine and Rehabilitation",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/physical-medicine-and-rehabilitation/",
        "attributes": {"category": "clinical"},
    },
    {
        "id": "department--medical-eye-bank",
        "name": "Eye Bank",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/eye-bank/",
        "attributes": {"category": "clinical"},
    },
    {
        "id": "department--medical-cardiovascular-and-thoracic-surgery",
        "name": "Cardio Vascular & Thoracic Surgery",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/cardio-thoracic-vascular-surgery/",
        "attributes": {"category": "super-speciality"},
    },
    {
        "id": "department--medical-neonatology",
        "name": "Neonatology",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/neonatology/",
        "attributes": {"category": "super-speciality"},
    },
    {
        "id": "department--allied-health-optometry",
        "name": "Optometry",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/optometry/",
        "attributes": {"category": "allied-health"},
    },
    {
        "id": "department--allied-health-clinical-psychology",
        "name": "Clinical Psychology",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/clinical-psychology/",
        "attributes": {"category": "allied-health"},
    },
    {
        "id": "department--allied-health-audiology-and-speech-language-pathology",
        "name": "Audiology and Speech-Language Pathology",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/audiology-and-speech-language-pathology/",
        "attributes": {"category": "allied-health"},
    },
    {
        "id": "department--allied-health-clinical-nutrition-and-dietetics",
        "name": "Clinical Nutrition and Dietetics",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/departments/clinical-nutrition-and-dietetics/",
        "attributes": {"category": "allied-health"},
    },
    {
        "id": "department--allied-health-medical-laboratory-technology",
        "name": "Medical Laboratory Technology",
        "parent_id": "sub_college--college-of-medicine",
        "attributes": {"category": "allied-health"},
    },
    {
        "id": "department--allied-health-neuro-sciences-technology",
        "name": "Neuro Sciences Technology",
        "parent_id": "sub_college--college-of-medicine",
        "attributes": {"category": "allied-health"},
    },
    {
        "id": "department--medical-simulation",
        "name": "Medical Simulation",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/medical-simulation/",
        "attributes": {"category": "medical-simulation"},
    },
    {
        "id": "department--medical-education",
        "name": "Medical Education Department",
        "parent_id": "sub_college--college-of-medicine",
        "url": "https://medical.srmist.edu.in/medical-education-department/",
        "attributes": {"category": "medical-education"},
    },
    {
        "id": "department--dental-anatomy",
        "name": "Anatomy",
        "parent_id": "sub_college--college-of-dentistry",
        "url": "https://dental.srmist.edu.in/basic-medical-science-departments/",
    },
    {
        "id": "department--dental-physiology",
        "name": "Physiology",
        "parent_id": "sub_college--college-of-dentistry",
        "url": "https://dental.srmist.edu.in/basic-medical-science-departments/",
    },
    {
        "id": "department--dental-biochemistry",
        "name": "Biochemistry",
        "parent_id": "sub_college--college-of-dentistry",
        "url": "https://dental.srmist.edu.in/basic-medical-science-departments/",
    },
    {
        "id": "department--dental-pharmacology",
        "name": "Pharmacology",
        "parent_id": "sub_college--college-of-dentistry",
        "url": "https://dental.srmist.edu.in/basic-medical-science-departments/",
    },
    {
        "id": "department--dental-microbiology",
        "name": "Microbiology",
        "parent_id": "sub_college--college-of-dentistry",
        "url": "https://dental.srmist.edu.in/basic-medical-science-departments/",
    },
    {
        "id": "department--dental-pathology",
        "name": "Pathology",
        "parent_id": "sub_college--college-of-dentistry",
        "url": "https://dental.srmist.edu.in/basic-medical-science-departments/",
    },
    {
        "id": "department--dental-general-medicine",
        "name": "General Medicine",
        "parent_id": "sub_college--college-of-dentistry",
        "url": "https://dental.srmist.edu.in/basic-medical-science-departments/",
    },
    {
        "id": "department--dental-general-surgery",
        "name": "General Surgery",
        "parent_id": "sub_college--college-of-dentistry",
        "url": "https://dental.srmist.edu.in/basic-medical-science-departments/",
    },
    {
        "id": "department--dental-research",
        "name": "Research",
        "parent_id": "sub_college--college-of-dentistry",
        "url": "https://dental.srmist.edu.in/dental-departments/",
    },
    {
        "id": "department--pharmacy-pharmaceutical-regulatory-affairs",
        "name": "Pharmaceutical Regulatory Affairs",
        "parent_id": "sub_college--college-of-pharmacy",
    },
    {
        "id": "department--pharmacy-pharmaceutical-quality-assurance",
        "name": "Pharmaceutical Quality Assurance",
        "parent_id": "sub_college--college-of-pharmacy",
    },
    {
        "id": "department--pharmacy-pharmacy-research",
        "name": "Pharmacy Research",
        "parent_id": "sub_college--college-of-pharmacy",
    },
]

_MEDICINE_TYPE_BY_CATEGORY = {
    "pre-and-para-clinical": "pre-and-para-clinical",
    "clinical": "clinical",
    "super-speciality": "super-speciality",
    "allied-health": "allied-health-science",
    "medical-simulation": "medical-simulation",
    "medical-education": "medical-education",
}
_DENTAL_BASIC_SCIENCE_IDS = {
    "department--dental-anatomy",
    "department--dental-physiology",
    "department--dental-biochemistry",
    "department--dental-pharmacology",
    "department--dental-microbiology",
    "department--dental-pathology",
    "department--dental-general-medicine",
    "department--dental-general-surgery",
}
for _dept in SEED_MEDICINE_DEPARTMENTS:
    _attrs = _dept.setdefault("attributes", {})
    _category = _attrs.get("category")
    if _dept["id"].startswith("department--medical-") or _dept["id"].startswith("department--allied-health-"):
        _type = _MEDICINE_TYPE_BY_CATEGORY.get(_category)
        if _type:
            _attrs["type"] = _type
        if _attrs.get("category") == _attrs.get("type"):
            _attrs.pop("category", None)
    elif _dept["id"] in _DENTAL_BASIC_SCIENCE_IDS:
        _attrs["type"] = "basic-medical-science"
    elif _dept["id"].startswith("department--dental-"):
        _attrs["type"] = "dental"

PROGRAM_PARENT_OVERRIDES: dict[str, str] = {
    "program--b-sc-biomedical-science": "department--department-of-biochemistry",
    "program--mbbs-bachelor-of-medicine-and-bachelor-of-surgery": "sub_college--college-of-medicine",
    "program--m-d-anatomy": "department--medical-anatomy",
    "program--m-sc-medical-anatomy": "department--medical-anatomy",
    "program--m-d-physiology": "department--medical-physiology",
    "program--m-sc-medical-physiology": "department--medical-physiology",
    "program--m-d-biochemistry": "department--medical-biochemistry",
    "program--m-sc-medical-biochemistry": "department--medical-biochemistry",
    "program--m-d-pharmacology": "department--medical-pharmacology",
    "program--m-d-pathology": "department--medical-pathology",
    "program--m-d-microbiology": "department--medical-microbiology",
    "program--m-sc-medical-microbiology": "department--medical-microbiology",
    "program--md-forensic-medicine-toxicology": "department--medical-forensic-medicine",
    "program--m-d-community-medicine": "department--medical-community-medicine",
    "program--m-d-general-medicine": "department--medical-general-medicine",
    "program--m-d-paediatrics": "department--medical-paediatrics",
    "program--m-d-psychiatry": "department--medical-psychiatry",
    "program--m-d-dermatology-venerology-and-leprosy": "department--medical-dermatology",
    "program--m-d-respiratory-medicine": "department--medical-respiratory-medicine",
    "program--m-s-general-surgery": "department--medical-general-surgery",
    "program--m-s-orthopaedics": "department--medical-orthopaedics",
    "program--m-s-otorhinolaryngology-ent": "department--medical-ent",
    "program--m-s-ophthalmology": "department--medical-ophthalmology",
    "program--m-s-obstetrics-and-gynaecology": "department--medical-obstetrics-and-gynaecology",
    "program--m-d-anaesthesiology": "department--medical-anaesthesia",
    "program--m-d-radio-diagnosis": "department--medical-radio-diagnosis",
    "program--md-emergency-medicine": "department--medical-emergency-medicine",
    "program--fellowship-emergency-medicine": "department--medical-emergency-medicine",
    "program--m-d-immuno-haematology-blood-transfusion": "department--medical-transfusion-medicine",
    "program--d-m-cardiology": "department--medical-cardiology",
    "program--d-m-nephrology": "department--medical-nephrology",
    "program--d-m-neurology": "department--medical-neurology",
    "program--m-ch-neuro-surgery": "department--medical-neurosurgery",
    "program--m-ch-urology": "department--medical-urology",
    "program--m-sc-urology-technology": "department--medical-urology",
    "program--m-ch-plastic-and-reconstructive-surgery": "department--medical-plastic-and-reconstructive-surgery",
    "program--m-ch-peadiatric-surgery": "department--medical-paediatric-surgery",
    "program--dm-medical-gastroenterology": "department--medical-medical-gastroenterology",
    "program--m-ch-cardio-vascular-and-thoracic-surgery": "department--medical-cardiovascular-and-thoracic-surgery",
    "program--m-ch-cardiothoracic-vascular-surgery": "department--medical-cardiovascular-and-thoracic-surgery",
    "program--b-sc-cardio-perfusion-technology": "department--medical-cardiovascular-and-thoracic-surgery",
    "program--m-sc-perfusion-technology": "department--medical-cardiovascular-and-thoracic-surgery",
    "program--dm-critical-care-medicine": "department--medical-critical-care-medicine",
    "program--b-sc-critical-care-technology": "department--medical-critical-care-medicine",
    "program--m-sc-critical-care-technology": "department--medical-critical-care-medicine",
    "program--m-sc-nurse-practitioner-in-critical-care-npcc": "department--medical-critical-care-medicine",
    "program--b-sc-accident-and-emergency-care-technology": "department--medical-emergency-medicine",
    "program--b-sc-neuro-sciences-technology": "department--allied-health-neuro-sciences-technology",
    "program--m-sc-neuroscience-technology": "department--allied-health-neuro-sciences-technology",
    "program--b-sc-renal-dialysis-technology": "department--medical-nephrology",
    "program--m-sc-renal-science-and-dialysis-technology": "department--medical-nephrology",
    "program--b-sc-medical-imaging-technology": "department--medical-radio-diagnosis",
    "program--m-sc-medical-imaging-technology": "department--medical-radio-diagnosis",
    "program--b-sc-medical-laboratory-technology": "department--allied-health-medical-laboratory-technology",
    "program--m-sc-medical-laboratory-technology": "department--allied-health-medical-laboratory-technology",
    "program--b-sc-respiratory-therapy": "department--medical-respiratory-medicine",
    "program--m-sc-respiratory-therapy": "department--medical-respiratory-medicine",
    "program--m-sc-clinical-research": "sub_college--college-of-medicine",
    "program--best-m-sc-biochemistry-colleges-chennai": "department--department-of-biochemistry",
    "program--ph-d-in-biochemistry": "department--department-of-biochemistry",
}

PROGRAM_PARENT_OVERRIDES.update({
    "program--b-optom-optometry": "department--allied-health-optometry",
    "program--m-optm-optometry": "department--allied-health-optometry",
    "program--ph-d-optometry": "department--allied-health-optometry",
    "program--b-a-s-l-audiology-and-speech-language-pathology": "department--allied-health-audiology-and-speech-language-pathology",
    "program--m-sc-audiology": "department--allied-health-audiology-and-speech-language-pathology",
    "program--m-sc-speech-language-and-pathology": "department--allied-health-audiology-and-speech-language-pathology",
    "program--ph-d-clinical-psychology": "department--allied-health-clinical-psychology",
    "program--b-sc-clinical-nutrition-and-dietetics": "department--allied-health-clinical-nutrition-and-dietetics",
    "program--m-sc-clinical-nutrition-and-dietetics": "department--allied-health-clinical-nutrition-and-dietetics",
    "program--bachelor-of-dental-surgery": "sub_college--college-of-dentistry",
    "program--m-d-s-oral-and-maxillofacial-surgery": "department--dental-oral-and-maxillofacial-surgery",
    "program--m-d-s-oral-pathology": "department--dental-oral-and-maxillofacial-pathology",
    "program--m-d-s-prosthodontics-and-crown-bridge": "department--dental-prosthodontics-and-crown-and-bridge",
    "program--m-d-s-periodontics": "department--dental-periodontology",
    "program--m-d-s-orthodontics-dento-facial-orthopeadics": "department--dental-orthodontics-and-dentofacial-orthopedics",
    "program--m-d-s-conservative-dentistry-and-endodontics": "department--dental-conservative-dentistry-and-endodontics",
    "program--m-d-s-paediatric-preventive-dentistry": "department--dental-pediatric-and-preventive-dentistry",
    "program--m-d-s-public-health-dentistry": "department--dental-public-health-dentistry",
    "program--m-d-s-oral-medicine-radiology": "department--dental-oral-medicine-and-radiology",
    "program--b-pharm-pharmacy": "sub_college--college-of-pharmacy",
    "program--ph-d-in-pharmacy": "department--pharmacy-pharmacy-research",
    "program--m-pharm-pharmaceutics": "department--pharmacy-pharmaceutics",
    "program--m-pharm-pharmaceutical-analysis": "department--pharmacy-pharmaceutical-analysis",
    "program--m-pharm-pharmaceutical-chemistry": "department--pharmacy-pharmaceutical-chemistry",
    "program--m-pharm-pharmacology": "department--pharmacy-pharmacology",
    "program--m-pharm-pharmacognosy": "department--pharmacy-pharmacognosy",
    "program--m-pharm-pharmacy-practice": "department--pharmacy-pharmacy-practice",
    "program--pharmd-doctor-of-pharmacy": "department--pharmacy-pharmacy-practice",
    "program--pharm-d": "department--pharmacy-pharmacy-practice",
    "program--m-pharm-pharmaceutical-quality-assurance": "department--pharmacy-pharmaceutical-quality-assurance",
    "program--m-pharm-pharmaceutical-regulatory-affairs": "department--pharmacy-pharmaceutical-regulatory-affairs",
    "program--b-p-t-bachelor-of-physiotherapy": "sub_college--college-of-physiotherapy",
    "program--ph-d-physiotherapy": "sub_college--college-of-physiotherapy",
    "program--m-p-t-neurology": "sub_college--college-of-physiotherapy",
    "program--m-p-t-sports-physiotherapy": "sub_college--college-of-physiotherapy",
    "program--b-sc-nursing": "sub_college--college-of-nursing",
    "program--pbb-sc-nursing": "sub_college--college-of-nursing",
    "program--diploma-in-nursing-dgnm": "sub_college--college-of-nursing",
    "program--m-sc-medical-surgical-nursing": "sub_college--college-of-nursing",
    "program--m-sc-community-health-nursing": "sub_college--college-of-nursing",
    "program--m-sc-obstertrics-and-gynaecology-nursing": "sub_college--college-of-nursing",
    "program--m-sc-paediatric-nursing": "sub_college--college-of-nursing",
    "program--m-sc-psychiatric-nursing": "sub_college--college-of-nursing",
    "program--post-basic-diploma-critical-care-nursing": "sub_college--college-of-nursing",
    "program--post-basic-diploma-operation-room-nursing": "sub_college--college-of-nursing",
    "program--post-basic-diploma-emergency-and-disaster-nursing": "sub_college--college-of-nursing",
    "program--bachelor-of-occupational-therapy": "sub_college--college-of-occupational-therapy",
    "program--ph-d-occupational-therapy": "sub_college--college-of-occupational-therapy",
    "program--m-o-t-neurosciences": "sub_college--college-of-occupational-therapy",
    "program--integrated-master-of-public-health": "sub_college--school-of-public-health",
    "program--master-of-public-health-mph": "sub_college--school-of-public-health",
    "program--mph-applied-health-research": "sub_college--school-of-public-health",
    "program--ph-d-public-health": "sub_college--school-of-public-health",
    "program--msc-biostatistics-and-epidemiology": "sub_college--school-of-public-health",
    "program--m-sc-health-data-science": "sub_college--school-of-public-health",
    "program--best-b-com-information-system-and-management-chennai": "department--department-of-corporate-secretaryship-and-accounting-finance",
    "program--b-com-w-s-business-analytics": "department--department-of-corporate-secretaryship-and-accounting-finance",
    "program--b-tech-ece-with-specialization-in-cyber-physical-systems": "department--department-of-electronics-communication",
    "program--computer-aided-diagnostics": "department--department-of-biomedical-engineering",
    "program--electric-vehicle-technology": "department--department-of-electrical-and-electronics-engineering",
    "program--imaging-sciences-and-machine-vision": "department--department-of-networking-and-communications",
    "program--m-b-a-business-analytics": "department--department-of-management",
    "program--m-tech-electric-vehicle-technology-in-collaboration-with-valeo": "department--department-of-electrical-and-electronics-engineering",
    "program--phd-in-management": "department--department-of-management",
})

SEED_ADDITIONAL_DEPARTMENTS = [
    {
        "id": "department--department-of-computer-science-and-engineering",
        "name": "Computer Science and Engineering",
        "parent_id": "school--school-of-computing",
    },
    {
        "id": "department--department-of-interior-design",
        "name": "Interior Design",
        "parent_id": "school--school-of-architecture-and-interior-design",
    },
    {
        "id": "department--department-of-management",
        "name": "Management",
        "parent_id": "college--faculty-of-management",
    },
]

PROGRAM_PARENT_PATTERNS: list[tuple[str, str]] = [
    (r"associate fellow of industrial health|afih", "department--medical-community-medicine"),
    (r"hospital administration", "sub_college--school-of-public-health"),
    (r"reproductive medicine|clinical embryology", "department--medical-obstetrics-and-gynaecology"),
    (r"cardiac care|cardiovascular sciences", "department--medical-cardiology"),
    (r"anaesthesia|operation theatre", "department--medical-anaesthesia"),
    (r"physician associate|advance care paramedics", "sub_college--college-of-medicine"),
    (r"m\.o\.t.*hand", "sub_college--college-of-occupational-therapy"),
    (r"m\.o\.t.*mental", "sub_college--college-of-occupational-therapy"),
    (r"m\.o\.t.*orthopaedics", "sub_college--college-of-occupational-therapy"),
    (r"m\.o\.t.*paediatrics|m\.o\.t.*pediatrics", "sub_college--college-of-occupational-therapy"),
    (r"m\.p\.t.*community", "sub_college--college-of-physiotherapy"),
    (r"m\.p\.t.*cardio", "sub_college--college-of-physiotherapy"),
    (r"m\.p\.t.*obstetrics", "sub_college--college-of-physiotherapy"),
    (r"m\.p\.t.*musculoskeletal|m\.p\.t.*orthopaedics", "sub_college--college-of-physiotherapy"),
    (r"m\.p\.t.*pediatric|m\.p\.t.*paediatric", "sub_college--college-of-physiotherapy"),
    (r"b\.b\.a\.,ll\.b|ll\.b|ll\.m|legum|criminal law", "department--department-of-law"),
    (r"\bb\.ed\.", "department--school-of-education"),
    (r"journalism|mass communication", "department--department-of-journalism-and-mass-communication"),
    (r"\benglish\b", "department--department-of-english"),
    (r"visual communication", "department--department-of-visual-communication"),
    (r"fashion", "department--department-of-fashion-designing"),
    (r"defence|strategic studies", "department--department-of-defence-and-strategic-studies"),
    (r"master of social work|\bmsw\b|social work", "department--department-of-social-work"),
    (r"ph\.d\. tamil|\btamil\b", "department--department-of-tamil"),
    (r"language, linguistics|language linguistics|literature", "department--department-of-language-culture-and-society"),
    (r"psychology|counselling psychology|behavioral psychology|sports and exercise psychology", "department--department-of-psychology"),
    (r"\bpublic policy\b|\bmpp\b|\beconomics\b", "department--department-of-economics"),
    (r"physical education|health education and sports", "department--department-of-physical-education-sports-sciences"),
    (r"b\.com\. general|\bcommerce\b", "department--department-of-commerce"),
    (r"corporate secretaryship|accounting|finance|banking|taxation|professional accounting|information system and management|certified financial management|strategic finance", "department--department-of-corporate-secretaryship-and-accounting-finance"),
    (r"computer applications|\bbca\b|\bmca\b", "department--department-of-computer-applications"),
    (r"computer science engineering|\bcse\b|full stack", "department--department-of-computer-science-and-engineering"),
    (r"agentic ai|artificial intelligence|machine learning|immersive technologies", "department--department-of-computational-intelligence"),
    (r"big data|data science|applied data science|financial technologies", "department--department-of-data-science-and-business-systems"),
    (r"cyber security|cyber forensics|information security|cloud|network|internet of things|\biot\b", "department--department-of-networking-and-communications"),
    (r"computer science|information technology", "department--department-of-computer-science"),
    (r"electronics and communication|electronics & communication|electronics & computer engineering|micro electronics|vlsi|embedded|wireless communication", "department--department-of-electronics-communication"),
    (r"instrumentation|industrial automation", "department--department-of-electronics-instrumentation"),
    (r"electrical|power electronics|power systems|solar energy", "department--department-of-electrical-and-electronics-engineering"),
    (r"aerospace|aeronautical|space technology|drone technology", "department--department-of-aerospace-engineering"),
    (r"automobile|automotive", "department--department-of-automobile-engineering"),
    (r"mechatronics|robotics|automation|biosustainability|green energy and environmental engineering|semiconductor process engineering", "department--department-of-mechatronics"),
    (r"mechanical engineering|additive manufacturing|computer aided design|thermal engineering|electronic cooling", "department--department-of-mechanical-engineering"),
    (r"civil engineering|construction engineering|geotechnical|structural engineering|environmental engineering|remote sensing", "department--department-of-civil-engineering"),
    (r"architecture|public space design", "department--department-of-architecture"),
    (r"interior design", "department--department-of-interior-design"),
    (r"biomedical engineering|medical device|assistive technology|computer aided diagnostics", "department--department-of-biomedical-engineering"),
    (r"genetic engineering|genetic counseling", "department--department-of-genetic-engineering"),
    (r"food safety|food process engineering|food technology|nutritional biotechnology", "department--department-of-food-technology"),
    (r"chemical engineering", "department--department-of-chemical-engineering"),
    (r"nanotechnology|quantum technologies|semiconductor technology|material science and engineering", "department--department-of-physics-and-nanotechnology"),
    (r"computational biology|regenerative medicine|m\.tech\. bio technology|biotechnology", "department--department-of-biotechnology"),
    (r"\bchemistry\b", "department--department-of-chemistry"),
    (r"\bphysics\b", "department--department-of-physics-and-nanotechnology"),
    (r"mathematics|statistics", "department--department-of-mathematics-and-statistics"),
    (r"biochemistry", "department--department-of-biochemistry"),
    (r"\byoga\b", "department--department-of-yoga"),
    (r"culinary arts|hotel|catering", "department--institute-of-hotel-and-catering-management"),
    (r"disaster management", "department--department-of-social-work"),
    (r"agricultural extension", "department--department-of-agricultural-extension-education"),
    (r"agricultural economics", "department--department-of-agricultural-economics"),
    (r"agronomy|agriculture", "department--department-of-agronomy"),
    (r"entomology", "department--department-of-entomology"),
    (r"plant pathology", "department--department-of-plant-pathology"),
    (r"soil science", "department--dept-of-soil-science-and-agricultural-chemistry"),
    (r"genetics and plant breeding", "department--department-of-genetics-and-plant-breeding"),
    (r"floriculture", "department--department-of-floriculture-and-landscaping"),
    (r"fruit science", "department--department-of-fruit-science"),
    (r"vegetable science", "department--department-of-vegetable-science"),
    (r"horticulture", "department--department-of-horticulture"),
    (r"management studies|\bmms\b|bba|mba|digital marketing|sports management|financial services|logistics|supply chain|fintech", "department--department-of-management"),
]

CENTRE_PARENT_OVERRIDES: dict[str, str] = {
    "centre--centre-for-research-in-defence-and-international-studies": "department--department-of-defence-and-strategic-studies",
    "centre--centre-for-research-in-environment-sustainability-advocacy-and-climate-change-reach": "department--department-of-natural-resources-management",
    "centre--career-centre": "directorate--directorate-of-career-centre",
    "centre--srm-medical-research-centre": "directorate--directorate-of-research",
    "centre--active-learning-lab": "department--school-of-education",
    "centre--adl-lab": "sub_college--college-of-occupational-therapy",
    "centre--advance-multilingual-computing": "department--department-of-computational-intelligence",
    "centre--agricultural-microbiology-and-environmental-science": "department--department-of-agronomy",
    "centre--ai-dl-lab-based-on-nvidia-dgx-a100": "department--department-of-computational-intelligence",
    "centre--biomechanics-lab": "sub_college--college-of-physiotherapy",
    "centre--block-chain-technology-lab-with-ids-inc": "department--department-of-computer-science-and-engineering",
    "centre--center-for-acces": "sub_college--college-of-occupational-therapy",
    "centre--centre-for-computational-sustainability": "department--department-of-computational-intelligence",
    "centre--charge-dynamics-laboratory-energy-materials-and-interfaces": "department--department-of-physics-and-nanotechnology",
    "centre--clinical-departments": "sub_college--college-of-medicine",
    "centre--composite-and-advanced-materials-manufacturing-lab": "department--department-of-mechanical-engineering",
    "centre--computing-and-design-centre": "department--department-of-computer-science-and-engineering",
    "centre--cyber-resilience-and-asset-intelligence-lab": "department--department-of-networking-and-communications",
    "centre--dst-fist": "directorate--directorate-of-research",
    "centre--dst-serb-funded-durability-studies-laboratory": "department--department-of-civil-engineering",
    "centre--electro-therapy-lab": "sub_college--college-of-physiotherapy",
    "centre--exercise-therapy-lab": "sub_college--college-of-physiotherapy",
    "centre--facilities-for-differently-abled-divyangjan-barrier-free-environment": "sub_college--college-of-occupational-therapy",
    "centre--functional-and-biomaterials-engineering-lab": "department--department-of-biomedical-engineering",
    "centre--hardware-trouble-shooting-lab": "department--department-of-networking-and-communications",
    "centre--intel-unnati-iot-soultions-lab": "department--department-of-networking-and-communications",
    "centre--materials-modelling-and-simulation-lab": "department--department-of-physics-and-nanotechnology",
    "centre--media-lab": "department--department-of-visual-communication",
    "centre--mtech-phd-research-lab": "directorate--directorate-of-research",
    "centre--nuclear-thermo-hydraulics-lab": "department--department-of-mechanical-engineering",
    "centre--nutrition-lab": "department--allied-health-clinical-nutrition-and-dietetics",
    "centre--orthopedic-lab": "sub_college--college-of-physiotherapy",
    "centre--post-graduate-research-lab": "directorate--directorate-of-research",
    "centre--radiation-measurement-lab": "department--department-of-physics-and-nanotechnology",
    "centre--research-and-development": "directorate--directorate-of-research",
    "centre--simulation-lab-2": "department--department-of-electronics-instrumentation",
    "centre--spdc": "directorate--directorate-of-learning-and-development",
    "centre--tissue-engineering-and-cancer-research-laboratory": "department--department-of-biomedical-engineering",
    "centre--transgenic-green-house-built-as-per-the-specifications-of-the-dbt-govt-of-india": "department--department-of-genetic-engineering",
}

CENTRE_URL_PARENT_OVERRIDES: dict[str, str] = {
    "school-of-public-health": "sub_college--school-of-public-health",
    "college-of-nursing": "sub_college--college-of-nursing",
    "college-of-occupational-therapy": "sub_college--college-of-occupational-therapy",
}

CENTRE_PARENT_PATTERNS: list[tuple[str, str]] = [
    (r"community health nursing", "sub_college--college-of-nursing"),
    (r"medical surgical nursing", "sub_college--college-of-nursing"),
    (r"obstetrics|gynecolog|gynaecolog", "sub_college--college-of-nursing"),
    (r"paediatric nursing", "sub_college--college-of-nursing"),
    (r"psychiatric nursing", "sub_college--college-of-nursing"),
    (r"fundamentals of nursing|computer lab nursing", "sub_college--college-of-nursing"),
    (r"orthopaed|musculoskeletal", "sub_college--college-of-physiotherapy"),
    (r"cardiopulmonary", "sub_college--college-of-physiotherapy"),
    (r"neurology", "sub_college--college-of-physiotherapy"),
    (r"sports lab", "sub_college--college-of-physiotherapy"),
    (r"paediatrics", "sub_college--college-of-physiotherapy"),
    (r"community rehabilitation", "sub_college--college-of-physiotherapy"),
    (r"hand rehabilitation", "sub_college--college-of-occupational-therapy"),
    (r"mental health", "sub_college--college-of-occupational-therapy"),
    (r"neuro rehabilitation", "sub_college--college-of-occupational-therapy"),
    (r"pharmaceutical analysis", "department--pharmacy-pharmaceutical-analysis"),
    (r"pharmaceutical chemistry", "department--pharmacy-pharmaceutical-chemistry"),
    (r"pharmaceutics", "department--pharmacy-pharmaceutics"),
    (r"pharmacognosy", "department--pharmacy-pharmacognosy"),
    (r"pharmacology", "department--pharmacy-pharmacology"),
    (r"food ", "department--department-of-food-technology"),
    (r"genetic|genomics", "department--department-of-genetic-engineering"),
    (r"biotechnology|bioseparation", "department--department-of-biotechnology"),
    (r"concrete|remote sensing|gis|structural|geotechnical|asphalt|durability", "department--department-of-civil-engineering"),
    (r"aerodynamic|uav|space|aerospace", "department--department-of-aerospace-engineering"),
    (r"automobile", "department--department-of-automobile-engineering"),
    (r"mechatronics|robotic", "department--department-of-mechatronics"),
    (r"cad lab|heat transfer|smithy|foundry|mechanical operation|product development|thermo|manufacturing", "department--department-of-mechanical-engineering"),
    (r"electronic|embedded|rf |microwave|vlsi|signal processing|pcb|wireless|semiconductor", "department--department-of-electronics-communication"),
    (r"instrument|control|sensor|industrial automation|simulation", "department--department-of-electronics-instrumentation"),
    (r"electrical|charging|power electronics", "department--department-of-electrical-and-electronics-engineering"),
    (r"programming|compiler|object oriented|graphics|software development|data structure|operating system|rdbms|assembly|microprocessor|open source|internet programming|computer lab|it lab|office suite|block chain", "department--department-of-computer-science-and-engineering"),
    (r"artificial intelligence|ai |computer vision|accelerated computing|theoretical computer science|visual computing|edge intelligence|quantum computing|tamil computing|multilingual computing|agentic", "department--department-of-computational-intelligence"),
    (r"network|cyber security|cloud|iot", "department--department-of-networking-and-communications"),
    (r"data mining|green computing", "department--department-of-data-science-and-business-systems"),
    (r"media lab", "department--department-of-visual-communication"),
    (r"child rights", "sub_college--school-of-public-health"),
    (r"research", "directorate--directorate-of-research"),
]

PROGRAM_PARENT_OVERRIDES.update({
    "program--m-tech-big-data-analytics": "department--department-of-data-science-and-business-systems",
    "program--m-tech-in-big-data-analytics": "department--department-of-data-science-and-business-systems",
    "program--phd-in-biotechnology": "department--department-of-biotechnology",
})

PROGRAM_DETACHED_IDS: set[str] = {
    "program--regular-phd",
}

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
        "url": "https://www.srmist.edu.in/research/",
    },
    {
        "id": "directorate--controller-of-examinations",
        "name": "Controller of Examinations",
        "url": "https://www.srmist.edu.in/controller-of-examinations/",
    },
    {
        "id": "directorate--directorate-of-alumni-affairs",
        "name": "Directorate of Alumni Affairs",
        "url": "https://www.srmist.edu.in/alumni-affairs/",
    },
    {
        "id": "directorate--directorate-of-communications",
        "name": "Directorate of Communications",
        "url": "https://www.srmist.edu.in/directorate-of-communications/",
    },
    {
        "id": "directorate--directorate-of-career-centre",
        "name": "Directorate of Career Centre",
        "url": "https://www.srmist.edu.in/career-centre/",
    },
    {
        "id": "directorate--itkm",
        "name": "Information Technology and Knowledge Management (ITKM)",
        "url": "https://www.srmist.edu.in/itkm/",
    },
    {
        "id": "directorate--directorate-of-learning-and-development",
        "name": "Directorate of Learning and Development",
        "url": "https://dld.srmist.edu.in/",
    },
    {
        "id": "directorate--directorate-of-campus-administration",
        "name": "Directorate of Campus Administration & Facilities",
        "url": "https://www.srmist.edu.in/about-us/administrative-heads/director-campus-administration/",
    },
    {
        "id": "directorate--directorate-of-distance-education",
        "name": "Directorate of Distance Education",
        "url": "https://www.srmist.edu.in/directorate-of-online-and-distance-education-dode/",
    },
    {
        "id": "directorate--directorate-of-online-education",
        "name": "Directorate of Online Education",
        "url": "https://www.srmist.edu.in/directorate-of-online-and-distance-education-dode/",
    },
    {
        "id": "directorate--directorate-of-entrepreneurship-and-innovation",
        "name": "Directorate of Entrepreneurship and Innovation",
        "url": "https://www.srmdei.com/",
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
    # CDC centres are academically owned by their college and secondarily listed
    # under the Directorate of Career Centre.
    ("centre--cdc-cet", "directorate--directorate-of-career-centre", "also_listed_under"),
    ("centre--cdc-csh", "directorate--directorate-of-career-centre", "also_listed_under"),
]

# ---------------------------------------------------------------------------
# Directorate of Research overrides
# ---------------------------------------------------------------------------

_RESEARCH_DIRECTORATE_ID = "directorate--directorate-of-research"

# These centres are tracked under the Directorate of Research, but if the site
# explicitly lists them under a college/department, that academic context
# should become the primary parent and Research should remain a secondary link.
RESEARCH_DIRECTORATE_CENTRES = [
    {
        "id": "centre--iiism",
        "name": "Interdisciplinary Institute of Indian System of Medicine (IIISM)",
        "url": "https://www.srmist.edu.in/research/research-wings/iiism/",
        "aliases": ["iism", "iiism"],
    },
    {
        "id": "centre--reach",
        "name": "REACH",
        "url": "https://www.srmist.edu.in/research/research-wings/reach/",
        "aliases": ["reach"],
    },
    {
        "id": "centre--nanotechnology-research-center",
        "name": "Nanotechnology Research Center (NRC)",
        "url": "https://www.srmist.edu.in/research/research-wings/nrc/",
        "aliases": ["nrc", "nanotechnology-research-center"],
    },
    {
        "id": "centre--cacr",
        "name": "Centre For Advanced Concrete Research (CACR)",
        "url": "https://www.srmist.edu.in/research/research-wings/cacr/",
        "aliases": ["cacr"],
    },
    {
        "id": "centre--srm-dbt-platform",
        "name": "SRM-DBT Platform",
        "url": "https://www.srmist.edu.in/department/srm-dbt-platform/",
        "aliases": ["srm-dbt-platform", "srm-dbt", "dbt-platform"],
    },
    {
        "id": "centre--medical-research-centre",
        "name": "Medical Research Centre (aMRC)",
        "url": "https://www.srmist.edu.in/research/research-wings/mrc/",
        "aliases": ["mrc", "amrc", "medical-research-centre", "medical-research-center"],
    },
    {
        "id": "centre--centre-for-statistics",
        "name": "Centre for Statistics",
        "url": "https://www.srmist.edu.in/research/research-wings/centre-for-statistics/",
        "aliases": ["centre-for-statistics", "center-for-statistics"],
    },
    {
        "id": "centre--eqrc",
        "name": "Environmental Quality Research Centre (EQRC)",
        "url": "https://www.srmist.edu.in/research/research-wings/eqrc/",
        "aliases": ["eqrc", "erc"],
    },
    {
        "id": "centre--hpcc",
        "name": "High Performance Computing Centre (HPCC)",
        "url": "https://www.srmist.edu.in/research/hpcc/",
        "aliases": ["hpcc"],
    },
    {
        "id": "centre--scif",
        "name": "SCIF",
        "url": "https://www.srmist.edu.in/research/scif/",
        "aliases": ["scif"],
    },
]

RESEARCH_DIRECTORATE_PAGES = [
    {
        "id": "misc--research-and-development-cell",
        "name": "Research and Development Cell",
        "entity_type": "misc",
        "url": "https://www.srmist.edu.in/research/research-and-development-cell/",
        "attributes": {"domain": "research", "cluster": "governance"},
    },
    {
        "id": "misc--university-research-council",
        "name": "University Research Council",
        "entity_type": "misc",
        "url": "https://www.srmist.edu.in/research/university-research-council/",
        "attributes": {"domain": "research", "cluster": "governance"},
    },
    {
        "id": "misc--research-projects",
        "name": "Research Projects",
        "entity_type": "misc",
        "url": "https://www.srmist.edu.in/research/projects/",
        "attributes": {"domain": "research", "cluster": "projects"},
    },
    {
        "id": "misc--sponsored-projects",
        "name": "Sponsored Projects",
        "entity_type": "misc",
        "url": "https://www.srmist.edu.in/research/sponsored-projects/",
        "attributes": {"domain": "research", "cluster": "projects"},
    },
    {
        "id": "misc--seri",
        "name": "Selective Excellence Research Initiative (SERI)",
        "entity_type": "misc",
        "url": "https://www.srmist.edu.in/research/seri/",
        "attributes": {"domain": "research", "cluster": "initiative"},
    },
    {
        "id": "publication--research-publications",
        "name": "Research Publications",
        "entity_type": "publication",
        "url": "https://www.srmist.edu.in/research/publications/",
        "attributes": {"domain": "research", "cluster": "publication-archive"},
    },
    {
        "id": "publication--research-patents",
        "name": "Research Patents",
        "entity_type": "publication",
        "url": "https://www.srmist.edu.in/research/patents/",
        "attributes": {"domain": "research", "cluster": "patents"},
    },
    {
        "id": "misc--phd-awarded",
        "name": "Ph.D Awarded",
        "entity_type": "misc",
        "url": "https://www.srmist.edu.in/research/ph-d-awarded/",
        "attributes": {"domain": "research", "cluster": "doctoral"},
    },
    {
        "id": "misc--dr-paarivendhar-research-colloquium",
        "name": "Dr. Paarivendhar Research Colloquium",
        "entity_type": "misc",
        "url": "https://www.srmist.edu.in/events/dprc/",
        "attributes": {"domain": "research", "cluster": "event"},
    },
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
    # School of Law page is the Department of Law under SRM School of Law.
    "school-of-law": "department--department-of-law",
    # Teacher Education and Research maps to School of Education department.
    "school-of-teacher-education-and-research": "department--school-of-education",
    # Mislisted as /department/ on some pages, but it is a directorate.
    "directorate-of-entrepreneurship-and-innovation": "directorate--directorate-of-entrepreneurship-and-innovation",
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

# Reviewed centre placements from manual duplicate-resolution passes.
# These rules preserve the intended structure even when site breadcrumbs or
# internal links are inconsistent across duplicate lab pages.
CENTRE_PARENT_OVERRIDES: dict[str, str] = {
    "centre--computer-lab": "department--department-of-architecture",
    "centre--computer-lab-2": "department--department-of-basic-sciences",
    "centre--computer-lab-nursing": "sub_college--college-of-nursing",
    "centre--civil-computer-lab": "department--department-of-civil-engineering",
    "centre--electronic-devices-and-circuits-laboratory": "department--department-of-mechatronics",
    "centre--genetic-engineering-lab-2": "department--department-of-genetic-engineering",
    "centre--hand-rehabilitation-lab": "college--faculty-of-management",
    "centre--microprocessor-lab": "department--department-of-electronics-communication",
    "centre--eie-microprocessor-lab": "department--department-of-electronics-instrumentation",
    "centre--networking-lab": "department--department-of-electronics-communication",
    "centre--paediatrics-lab": "sub_college--college-of-occupational-therapy",
    "centre--plant-virology-lab": "department--department-of-biotechnology",
    "centre--plant-virology-lab-2": "department--department-of-genetic-engineering",
    "centre--rdbms-lab-2": "department--department-of-networking-and-communications",
    "centre--robotics": "department--department-of-electronics-instrumentation",
    "centre--robotics-lab": "department--department-of-mechanical-engineering",
    "centre--advanced-robotics-laboratory": "department--department-of-mechatronics",
    "centre--soil-science-and-agricultural-chemistry": "department--department-of-natural-resources-management",
    "centre--stem-cell-biology-lab": "department--department-of-biotechnology",
    "centre--stem-cell-biology-lab-2": "department--department-of-genetic-engineering",
}

CENTRE_DETACHED_IDS: set[str] = {
    "centre--electronic-devices-and-circuits-laboratory2",
    "centre--genetic-engineering-lab",
    "centre--hand-rehabilitation-lab-2",
    "centre--microprocessor-lab-2",
    "centre--networking-lab-2",
    "centre--paediatrics-lab-2",
    "centre--rdbms-lab",
}

CENTRE_PARENT_OVERRIDES.update({
    "centre--centre-for-research-in-defence-and-international-studies": "department--department-of-defence-and-strategic-studies",
    "centre--centre-for-research-in-environment-sustainability-advocacy-and-climate-change-reach": "department--department-of-natural-resources-management",
    "centre--career-centre": "directorate--directorate-of-career-centre",
    "centre--srm-medical-research-centre": "directorate--directorate-of-research",
    "centre--active-learning-lab": "department--school-of-education",
    "centre--adl-lab": "sub_college--college-of-occupational-therapy",
    "centre--advance-multilingual-computing": "department--department-of-computational-intelligence",
    "centre--agricultural-microbiology-and-environmental-science": "department--department-of-agronomy",
    "centre--ai-dl-lab-based-on-nvidia-dgx-a100": "department--department-of-computational-intelligence",
    "centre--biomechanics-lab": "sub_college--college-of-physiotherapy",
    "centre--block-chain-technology-lab-with-ids-inc": "department--department-of-computer-science-and-engineering",
    "centre--center-for-acces": "sub_college--college-of-occupational-therapy",
    "centre--centre-for-computational-sustainability": "department--department-of-computational-intelligence",
    "centre--charge-dynamics-laboratory-energy-materials-and-interfaces": "department--department-of-physics-and-nanotechnology",
    "centre--clinical-departments": "sub_college--college-of-medicine",
    "centre--composite-and-advanced-materials-manufacturing-lab": "department--department-of-mechanical-engineering",
    "centre--computing-and-design-centre": "department--department-of-computer-science-and-engineering",
    "centre--cyber-resilience-and-asset-intelligence-lab": "department--department-of-networking-and-communications",
    "centre--dst-fist": "directorate--directorate-of-research",
    "centre--dst-serb-funded-durability-studies-laboratory": "department--department-of-civil-engineering",
    "centre--electro-therapy-lab": "sub_college--college-of-physiotherapy",
    "centre--exercise-therapy-lab": "sub_college--college-of-physiotherapy",
    "centre--facilities-for-differently-abled-divyangjan-barrier-free-environment": "sub_college--college-of-occupational-therapy",
    "centre--functional-and-biomaterials-engineering-lab": "department--department-of-biomedical-engineering",
    "centre--hardware-trouble-shooting-lab": "department--department-of-networking-and-communications",
    "centre--intel-unnati-iot-soultions-lab": "department--department-of-networking-and-communications",
    "centre--materials-modelling-and-simulation-lab": "department--department-of-physics-and-nanotechnology",
    "centre--media-lab": "department--department-of-visual-communication",
    "centre--mtech-phd-research-lab": "directorate--directorate-of-research",
    "centre--nuclear-thermo-hydraulics-lab": "department--department-of-mechanical-engineering",
    "centre--nutrition-lab": "department--allied-health-clinical-nutrition-and-dietetics",
    "centre--orthopedic-lab": "sub_college--college-of-physiotherapy",
    "centre--post-graduate-research-lab": "directorate--directorate-of-research",
    "centre--radiation-measurement-lab": "department--department-of-physics-and-nanotechnology",
    "centre--research-and-development": "directorate--directorate-of-research",
    "centre--simulation-lab-2": "department--department-of-electronics-instrumentation",
    "centre--spdc": "directorate--directorate-of-learning-and-development",
    "centre--tissue-engineering-and-cancer-research-laboratory": "department--department-of-biomedical-engineering",
    "centre--transgenic-green-house-built-as-per-the-specifications-of-the-dbt-govt-of-india": "department--department-of-genetic-engineering",
    "centre--industry-collaborators": "department--department-of-electrical-and-electronics-engineering",
})

_RESEARCH_CENTRE_ID_SET: set[str] = {c["id"] for c in RESEARCH_DIRECTORATE_CENTRES}
_RESEARCH_CENTRE_URL_PREFIX_TO_ID: dict[str, str] = {}
_RESEARCH_CENTRE_ALIAS_TO_ID: dict[str, str] = {}
for _centre in RESEARCH_DIRECTORATE_CENTRES:
    _RESEARCH_CENTRE_URL_PREFIX_TO_ID[_centre["url"].rstrip("/").lower()] = _centre["id"]
    _RESEARCH_CENTRE_ALIAS_TO_ID[_centre["id"].replace("centre--", "")] = _centre["id"]
    for _alias in _centre.get("aliases", []):
        _RESEARCH_CENTRE_ALIAS_TO_ID[_alias] = _centre["id"]

_RESEARCH_PAGE_URL_TO_RULE: dict[str, dict] = {
    rule["url"].rstrip("/").lower(): rule for rule in RESEARCH_DIRECTORATE_PAGES
}
_ENTITY_URL_OVERRIDES: dict[str, str] = {
    "campus--ramapuram": "https://srmrmp.edu.in/ramapuram-campus/",
    "centre--cdc-cet": "https://www.srmist.edu.in/department/cet-cdc/",
    "centre--cdc-csh": "https://www.srmist.edu.in/department/cdc-csh",
    "centre--cesd": "https://www.srmist.edu.in/department/cesd/",
    "centre--center-for-immersive-technologies": "https://www.srmist.edu.in/department/centre-for-immersive-technologies/",
    "centre--cacts": "https://www.srmist.edu.in/department/department-of-chemistry/centre-for-advanced-computational-and-theoretical-sciences-acts/",
    "centre--srm-brin-centre": "https://www.srmist.edu.in/department/srm-brin-centre-centre-of-excellence-in-automation-technologies/",
    "department--department-of-law": "https://www.srmist.edu.in/department/school-of-law/",
    "department--pharmacy-pharmaceutical-analysis": "https://www.srmist.edu.in/department/department-of-pharmaceutical-analysis/",
    "department--pharmacy-pharmaceutical-chemistry": "https://www.srmist.edu.in/department/department-of-pharmaceutical-chemistry/",
    "department--pharmacy-pharmaceutical-quality-assurance": "https://www.srmist.edu.in/department/department-of-pharmaceutical-quality-assurance/",
    "department--pharmacy-pharmaceutical-regulatory-affairs": "https://www.srmist.edu.in/department/department-of-pharmaceutical-regulatory-affairs/",
    "department--pharmacy-pharmaceutics": "https://www.srmist.edu.in/department/department-of-pharmaceutics/",
    "department--pharmacy-pharmacognosy": "https://www.srmist.edu.in/department/department-of-pharmacognosy/",
    "department--pharmacy-pharmacology": "https://medical.srmist.edu.in/departments/pharmacology/",
    "department--pharmacy-pharmacy-practice": "https://www.srmist.edu.in/department/department-of-pharmacy-practice/",
    "department--pharmacy-pharmacy-research": "https://www.srmist.edu.in/department/pharmacy-research/",
    "facility--housing": "https://www.srmist.edu.in/life-at-srm/student-life/housing-dining/",
    "facility--transport": "https://www.srmist.edu.in/transport-facility/",
    "facility--library": "https://www.srmist.edu.in/library/",
    "misc--news-and-events": "https://www.srmist.edu.in/news/",
    "misc--blog": "https://www.srmist.edu.in/blog/",
    "misc--about-srmist": "https://www.srmist.edu.in/about-us/",
    "misc--contact": "https://www.srmist.edu.in/contact-us/",
    "misc--careers-at-srm": "https://careers.srmist.edu.in/careerportal/careerportal/loginManager/applyJobs.jsp",
}
_DIRECTORATE_PAGE_URL_TO_ID: dict[str, str] = {
    "https://www.srmist.edu.in/research/innovation-incubation": "directorate--directorate-of-entrepreneurship-and-innovation",
    "https://www.srmdei.com": "directorate--directorate-of-entrepreneurship-and-innovation",
    "https://www.srmist.edu.in/about-us/administrative-heads/director-career-center": "directorate--directorate-of-career-centre",
    "https://www.srmist.edu.in/about/directorates/director-career-center": "directorate--directorate-of-career-centre",
    "https://www.srmist.edu.in/about-us/administrative-heads/director-alumni-relations": "directorate--directorate-of-alumni-affairs",
    "https://www.srmist.edu.in/about-us/administrative-heads/director-campus-administration": "directorate--directorate-of-campus-administration",
    "https://www.srmist.edu.in/controller-of-examinations": "directorate--controller-of-examinations",
    "https://www.srmist.edu.in/career-centre": "directorate--directorate-of-career-centre",
    "https://www.srmist.edu.in/alumni-affairs": "directorate--directorate-of-alumni-affairs",
    "https://www.srmist.edu.in/itkm": "directorate--itkm",
    "https://www.srmist.edu.in/itkm/": "directorate--itkm",
    "https://dld.srmist.edu.in": "directorate--directorate-of-learning-and-development",
    "https://dld.srmist.edu.in/": "directorate--directorate-of-learning-and-development",
    "https://www.srmist.edu.in/directorate-of-student-affairs": "directorate--directorate-of-student-affairs",
    "https://www.srmist.edu.in/directorate-of-student-affairs/": "directorate--directorate-of-student-affairs",
    "https://www.srmist.edu.in/directorate-of-communications": "directorate--directorate-of-communications",
    "https://www.srmist.edu.in/directorate-of-communications/": "directorate--directorate-of-communications",
    "https://www.srmist.edu.in/directorate-of-online-and-distance-education-dode": "directorate--directorate-of-online-education",
    "https://www.srmist.edu.in/directorate-of-online-and-distance-education-dode/": "directorate--directorate-of-online-education",
}

_KNOWN_CENTRE_SLUG_TO_ID: dict[str, str] = dict(_RESEARCH_CENTRE_ALIAS_TO_ID)
for _slug in _FET_CENTRE_SLUGS:
    _KNOWN_CENTRE_SLUG_TO_ID.setdefault(_slug, f"centre--{_slug}")
_KNOWN_CENTRE_SLUG_TO_ID["cdc-csh"] = "centre--cdc-csh"
_KNOWN_CENTRE_SLUG_TO_ID["cet-cdc"] = "centre--cdc-cet"


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

_HOD_PATTERN = re.compile(
    r"(?:Head\s+of\s+(?:the\s+)?Department|HoD|HOD)\s*[:\-–]?\s*"
    r"(?:Dr\.?\s*|Prof\.?\s*|Mr\.?\s*|Mrs\.?\s*|Ms\.?\s*)?"
    r"([A-Z][A-Za-z.\-' ]{2,40})",
    re.I,
)

_DEAN_PATTERN = re.compile(
    r"(?:Dean)\s*[:\-–]?\s*"
    r"(?:Dr\.?\s*|Prof\.?\s*|Mr\.?\s*|Mrs\.?\s*|Ms\.?\s*)?"
    r"([A-Z][A-Za-z.\-' ]{2,40})",
    re.I,
)

_CHAIRPERSON_PATTERN = re.compile(
    r"(?:Chairperson|Chair)\s*[:\-–]?\s*"
    r"(?:Dr\.?\s*|Prof\.?\s*|Mr\.?\s*|Mrs\.?\s*|Ms\.?\s*)?"
    r"([A-Z][A-Za-z.\-' ]{2,40})",
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
_ADMISSION_RE = re.compile(
    r"^https?://(?:www\.)?srmist\.edu\.in/admission-(india|international)/?$",
    re.I,
)
_PUBLICATION_RE = re.compile(
    r"srmist\.edu\.in/(publications|faculty-gateway)/?",
    re.I,
)
_LAB_RE = re.compile(
    r"^https?://(?:www\.)?srmist\.edu\.in/lab/([^/]+)/?$",
    re.I,
)

_HIGHER_ORDER_ENTITY_TYPES = {"directorate", "college", "department"}
_COLLABORATION_ENTITY_TYPES = {"centre", "program", "misc"}


# ---------------------------------------------------------------------------
# KnowledgeGraph
# ---------------------------------------------------------------------------

class KnowledgeGraph:

    def __init__(self):
        self.entities: dict[str, Entity] = {}
        self.relationships: list[Relationship] = []
        self.admission_profiles: dict[str, dict] = {}
        self._children_idx: dict[str, list[str]] = {}   # source_id -> [target_ids]
        self._parent_idx: dict[str, str] = {}            # target_id -> source_id
        self._name_idx: dict[str, str] = {}              # lowered name -> entity id

    # ----- mutation -----

    def add_entity(self, entity: Entity) -> None:
        self.entities[entity.id] = entity
        self._name_idx[entity.name.lower()] = entity.id

    def add_relationship(self, rel: Relationship) -> None:
        self._validate_relationship(rel)
        self.relationships.append(rel)
        self._children_idx.setdefault(rel.source_id, []).append(rel.target_id)
        _parent_rel_types = {
            "has_campus", "has_college", "has_sub_college",
            "has_department", "has_centre", "has_directorate",
            "has_facility", "has_admission_child", "belongs_to",
        }
        if rel.relation_type in _parent_rel_types:
            self._parent_idx[rel.target_id] = rel.source_id

    def _validate_relationship(self, rel: Relationship) -> None:
        if rel.relation_type != "collaborates_with":
            return

        source = self.entities.get(rel.source_id)
        target = self.entities.get(rel.target_id)
        if not source or not target:
            return

        invalid_types = {
            source.entity_type,
            target.entity_type,
        } & _HIGHER_ORDER_ENTITY_TYPES
        if invalid_types:
            raise ValueError(
                "Invalid collaborates_with edge between higher-order entities: "
                f"{rel.source_id} ({source.entity_type}) -> "
                f"{rel.target_id} ({target.entity_type})"
            )

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
        q = question.lower()

        target_entity = None
        for ent in sorted(self.entities.values(), key=lambda e: -len(e.name)):
            if ent.name.lower() in q and ent.entity_type in (
                "school", "college", "sub_college", "directorate"
            ):
                target_entity = ent
                break

        if not target_entity:
            return None

        # Try a sequence of progressively broader child lookups
        for rel in ("has_department", "has_sub_college", "has_centre", None):
            children = self.get_children(target_entity.id, rel)
            if children:
                break

        if not children:
            return None

        also_linked_ids = [
            r.source_id
            for r in self.relationships
            if r.target_id == target_entity.id and r.relation_type == "also_listed_under"
        ]
        also_linked = [
            self.entities[eid]
            for eid in also_linked_ids
            if eid in self.entities and eid not in {c.id for c in children}
        ]

        lines = [f"According to SRMIST records, {target_entity.name} includes:"]
        for child in sorted(children, key=lambda c: c.name):
            hod = child.attributes.get("hod", "")
            suffix = f" (HOD: {hod})" if hod else ""
            lines.append(f"- {child.name}{suffix}")
        for child in sorted(also_linked, key=lambda c: c.name):
            lines.append(f"- {child.name} (also listed here)")

        return "\n".join(lines)

    def derive_shared_lower_order_entities(
        self,
        left_entity_id: str,
        right_entity_id: str,
    ) -> list[Entity]:
        """Return lower-order entities shared by two higher-order parents."""
        left = self.entities.get(left_entity_id)
        right = self.entities.get(right_entity_id)
        if not left or not right:
            return []

        shared_ids: set[str] = set()
        for rel in self.relationships:
            if rel.relation_type not in ("has_centre", "offers_program", "also_listed_under"):
                continue

            if rel.source_id == left_entity_id and rel.relation_type in ("has_centre", "offers_program"):
                ent = self.entities.get(rel.target_id)
                if ent and ent.entity_type in _COLLABORATION_ENTITY_TYPES:
                    shared_ids.add(rel.target_id)
            if rel.source_id == right_entity_id and rel.relation_type in ("has_centre", "offers_program"):
                ent = self.entities.get(rel.target_id)
                if ent and ent.entity_type in _COLLABORATION_ENTITY_TYPES:
                    if rel.target_id in shared_ids:
                        continue
            if rel.relation_type == "also_listed_under" and rel.target_id in {left_entity_id, right_entity_id}:
                ent = self.entities.get(rel.source_id)
                if ent and ent.entity_type in _COLLABORATION_ENTITY_TYPES:
                    shared_ids.add(rel.source_id)

        shared_entities: list[Entity] = []
        for entity_id in sorted(shared_ids):
            linked_to_left = any(
                (r.source_id == left_entity_id and r.target_id == entity_id and r.relation_type in ("has_centre", "offers_program"))
                or (r.source_id == entity_id and r.target_id == left_entity_id and r.relation_type == "also_listed_under")
                for r in self.relationships
            )
            linked_to_right = any(
                (r.source_id == right_entity_id and r.target_id == entity_id and r.relation_type in ("has_centre", "offers_program"))
                or (r.source_id == entity_id and r.target_id == right_entity_id and r.relation_type == "also_listed_under")
                for r in self.relationships
            )
            if linked_to_left and linked_to_right and entity_id in self.entities:
                shared_entities.append(self.entities[entity_id])
        return shared_entities

    def answer_role_query(self, question: str) -> Optional[str]:
        """Try to answer 'Who is HOD/Dean of X?' from KG attributes."""
        q = question.lower()

        target_entity = None
        for ent in sorted(self.entities.values(), key=lambda e: -len(e.name)):
            if ent.name.lower() in q and ent.entity_type in (
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
            attributes={}, **sc,
        ))
        kg.add_relationship(Relationship(
            source_id="college--medicine-and-health-sciences",
            target_id=sc["id"],
            relation_type="has_sub_college",
        ))

    # 4b. Seed Medicine & Health Sciences departments and nested units
    for dept in SEED_MEDICINE_DEPARTMENTS:
        dept_id = dept["id"]
        parent_id = dept["parent_id"]
        attrs = dict(dept.get("attributes", {}))
        entity_kwargs = {
            "id": dept_id,
            "name": dept["name"],
            "entity_type": "department",
            "campus": "KTR",
            "url": dept.get("url", ""),
            "attributes": attrs,
        }
        if dept_id not in kg.entities:
            kg.add_entity(Entity(**entity_kwargs))
        else:
            kg.entities[dept_id].name = dept["name"]
            if dept.get("url"):
                kg.entities[dept_id].url = dept["url"]
            kg.entities[dept_id].attributes.update(attrs)
        kg.add_relationship(Relationship(
            source_id=parent_id,
            target_id=dept_id,
            relation_type="has_department",
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

    # 5b. Additional seeded departments not reliably exposed in scrape output
    for dept in SEED_ADDITIONAL_DEPARTMENTS:
        dept_id = dept["id"]
        parent_id = dept["parent_id"]
        if dept_id not in kg.entities:
            kg.add_entity(Entity(
                id=dept_id,
                name=dept["name"],
                entity_type="department",
                campus="KTR",
                url=dept.get("url", ""),
                attributes=dict(dept.get("attributes", {})),
            ))
        kg.add_relationship(Relationship(
            source_id=parent_id,
            target_id=dept_id,
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

    # 8b. Directorate of Research centres and structured pages
    for centre in RESEARCH_DIRECTORATE_CENTRES:
        attrs = {
            "domain": "research",
            "cluster": "research-centre",
            "aliases": centre.get("aliases", []),
        }
        if centre["id"] in kg.entities:
            kg.entities[centre["id"]].attributes.update(attrs)
            if not kg.entities[centre["id"]].url:
                kg.entities[centre["id"]].url = centre["url"]
        else:
            kg.add_entity(Entity(
                id=centre["id"],
                name=centre["name"],
                entity_type="centre",
                campus="KTR",
                url=centre["url"],
                attributes=attrs,
            ))
        if not _has_non_research_primary_parent(kg, centre["id"]):
            kg.add_relationship(Relationship(
                source_id=_RESEARCH_DIRECTORATE_ID,
                target_id=centre["id"],
                relation_type="has_centre",
            ))
        else:
            kg.add_relationship(Relationship(
                source_id=centre["id"],
                target_id=_RESEARCH_DIRECTORATE_ID,
                relation_type="also_listed_under",
            ))

    for rule in RESEARCH_DIRECTORATE_PAGES:
        kg.add_entity(Entity(
            id=rule["id"],
            name=rule["name"],
            entity_type=rule["entity_type"],
            campus="KTR",
            url=rule["url"],
            attributes=dict(rule.get("attributes", {})),
        ))
        kg.add_relationship(Relationship(
            source_id=rule["id"],
            target_id=_RESEARCH_DIRECTORATE_ID,
            relation_type="also_listed_under",
        ))

    kg.add_relationship(Relationship(
        source_id="misc--dr-paarivendhar-research-colloquium",
        target_id="misc--news-and-events",
        relation_type="also_listed_under",
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
        normalized_url = url.rstrip("/").lower()

        # ---- Explicit non-/directorate/ URL aliases for seeded directorates ----
        directorate_eid = _DIRECTORATE_PAGE_URL_TO_ID.get(normalized_url)
        if directorate_eid and directorate_eid in kg.entities:
            kg.entities[directorate_eid].url = url
            continue

        # ---- Research directorate exact pages ----
        if normalized_url == "https://www.srmist.edu.in/research":
            if _RESEARCH_DIRECTORATE_ID in kg.entities:
                kg.entities[_RESEARCH_DIRECTORATE_ID].url = url
            continue

        research_rule = _RESEARCH_PAGE_URL_TO_RULE.get(normalized_url)
        if research_rule:
            _upsert_rule_entity(kg, research_rule, campus, url)
            continue

        research_centre_id = _match_research_centre_url(url)
        if research_centre_id:
            _upsert_centre_entity(
                kg=kg,
                centre_id=research_centre_id,
                title=title,
                campus=campus,
                url=url,
            )
            _attach_centre_to_research(kg, research_centre_id)
            centre_pages[research_centre_id.replace("centre--", "")] = page
            continue

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
                centre_eid = _resolve_centre_id(sub_slug)
                dept_eid   = f"department--{dept_slug}"
                _upsert_centre_entity(
                    kg=kg,
                    centre_id=centre_eid,
                    title=title,
                    campus=campus,
                    url=url,
                )
                # Link to parent department
                if dept_eid in kg.entities:
                    _attach_centre_to_context(kg, dept_eid, centre_eid)
                if centre_eid in _RESEARCH_CENTRE_ID_SET:
                    _attach_centre_to_research(kg, centre_eid)
                centre_pages[centre_eid.replace("centre--", "")] = page
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
                centre_eid = _resolve_centre_id(slug)
                _upsert_centre_entity(
                    kg=kg,
                    centre_id=centre_eid,
                    title=title,
                    campus=campus,
                    url=url,
                )
                if centre_eid in _RESEARCH_CENTRE_ID_SET:
                    _attach_centre_to_research(kg, centre_eid)
                centre_pages[centre_eid.replace("centre--", "")] = page
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
            eid = _resolve_centre_id(slug)
            _upsert_centre_entity(
                kg=kg,
                centre_id=eid,
                title=title,
                campus=campus,
                url=url,
            )
            if eid in _RESEARCH_CENTRE_ID_SET:
                _attach_centre_to_research(kg, eid)
            centre_pages[eid.replace("centre--", "")] = page
            continue

        # ---- Lab pages (/lab/ URLs — often department-linked centres) ----
        m = _LAB_RE.match(url)
        if m:
            slug = m.group(1)
            eid = _resolve_centre_id(slug)
            _upsert_centre_entity(
                kg=kg,
                centre_id=eid,
                title=title,
                campus=campus,
                url=url,
            )
            centre_pages[eid.replace("centre--", "")] = page
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

    # --- Normalize known duplicate/misclassified nodes ---
    _normalize_known_entities(kg)

    # --- Apply reviewed centre ownership / loose-node decisions ---
    _apply_centre_parent_overrides(kg)

    # --- Apply deterministic program ownership fixes ---
    _apply_program_parent_overrides(kg)

    # --- Infer remaining orphan parent links for programs and centres ---
    _apply_orphan_program_inference(kg)
    _apply_orphan_centre_inference(kg)

    # --- Backfill missing entity URLs from the scraped corpus ---
    _backfill_entity_urls(kg, pages)

    # --- Enforce single-parent for departments and programs ---
    _enforce_single_parent(kg)

    # --- Build layered admissions graph + sidecar profiles ---
    kg.admission_profiles = integrate_admissions(kg, pages)

    # --- Deduplicate relationships ---
    _deduplicate_relationships(kg)

    log.info(f"KG built: {kg.stats()}")
    return kg


# ---------------------------------------------------------------------------
# Program CSV enrichment
# ---------------------------------------------------------------------------

def load_programs_from_csv(csv_path: str | Path, kg: "KnowledgeGraph") -> int:
    """Enrich existing KG program entities (or create new ones) from the programs CSV.

    Expected CSV columns: Title, URL, Duration, Annual Fees, Intake
    Returns the number of entities created or updated.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        log.warning(f"Programs CSV not found: {csv_path}")
        return 0

    # Collect all existing program entities with pre-computed token sets for matching
    existing_programs: list[tuple[str, frozenset[str]]] = [
        (eid, frozenset(_program_tokens(entity.name)))
        for eid, entity in kg.entities.items()
        if entity.entity_type == "program"
    ]

    updated = 0
    created = 0

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = _csv.DictReader(f)
        for row in reader:
            title = (row.get("Title") or "").strip()
            url = (row.get("URL") or "").strip()
            duration = (row.get("Duration") or "").strip()
            fees = (row.get("Annual Fees") or "").strip()
            intake = (row.get("Intake") or "").strip()

            if not title:
                continue

            csv_tokens = frozenset(_program_tokens(title))
            if not csv_tokens:
                continue

            # Find best-matching existing entity
            best_eid: str | None = None
            best_score = 0.0
            for eid, entity_tokens in existing_programs:
                score = _token_overlap(csv_tokens, entity_tokens)
                if score > best_score:
                    best_score = score
                    best_eid = eid

            if best_eid and best_score >= 0.5:
                entity = kg.entities[best_eid]
                # Enrich: set URL if missing, always update fees/duration/intake
                if not entity.url and url:
                    entity.url = url
                entity.attributes.setdefault("csv_url", url)
                if fees:
                    entity.attributes["annual_fees"] = fees
                if duration:
                    entity.attributes["duration"] = duration
                if intake:
                    entity.attributes["intake"] = intake
                updated += 1
            elif url:
                # Create a new program entity from the CSV row
                slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
                new_id = f"program--{slug}"
                # Avoid ID collisions
                if new_id in kg.entities:
                    new_id = f"program--csv-{slug}"
                new_entity = Entity(
                    id=new_id,
                    name=title,
                    entity_type="program",
                    campus="KTR",
                    url=url,
                    attributes={
                        "csv_url": url,
                        "annual_fees": fees,
                        "duration": duration,
                        "intake": intake,
                        "source": "programs_csv",
                    },
                )
                kg.add_entity(new_entity)
                # Refresh existing_programs list so subsequent rows can match this new entity
                existing_programs.append((new_id, csv_tokens))
                created += 1

    log.info(
        f"Programs CSV enrichment: {updated} entities updated, {created} new entities created "
        f"(from {csv_path.name})"
    )
    return updated + created


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
    centre_eid = _extract_centre_id_from_link(link)
    if centre_eid and centre_eid in kg.entities:
        if centre_eid in _RESEARCH_CENTRE_ID_SET:
            return
        _attach_centre_to_context(kg, source_eid, centre_eid)


def _deduplicate_relationships(kg: KnowledgeGraph) -> None:
    seen_rels: dict[tuple[str, str, str], int] = {}
    unique_rels: list[Relationship] = []
    for r in kg.relationships:
        key = (r.source_id, r.target_id, r.relation_type)
        if key not in seen_rels:
            seen_rels[key] = len(unique_rels)
            unique_rels.append(r)
            continue

        existing = unique_rels[seen_rels[key]]
        if r.relation_type == "admission_governs":
            existing_score = float(existing.metadata.get("match_confidence", 0) or 0)
            new_score = float(r.metadata.get("match_confidence", 0) or 0)
            if new_score > existing_score:
                unique_rels[seen_rels[key]] = r
    kg.relationships = unique_rels
    kg._children_idx.clear()
    kg._parent_idx.clear()
    _parent_rel_types = {
        "has_campus", "has_college", "has_sub_college",
        "has_department", "has_centre", "has_directorate",
        "has_facility", "has_admission_child", "belongs_to",
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


def _is_centre_slug(slug: str) -> bool:
    slug = slug.lower().strip("/")
    if slug in _KNOWN_CENTRE_SLUG_TO_ID:
        return True
    centre_tokens = (
        "centre", "center", "cdc", "lab", "laboratory", "platform",
        "hpcc", "scif", "iiism", "reach", "nrc", "mrc", "eqrc", "cacr",
    )
    return any(token in slug for token in centre_tokens)


def _resolve_centre_id(slug: str) -> str:
    slug = slug.lower().strip("/")
    return _KNOWN_CENTRE_SLUG_TO_ID.get(slug, f"centre--{slug}")


def _match_research_centre_url(url: str) -> Optional[str]:
    normalized = url.rstrip("/").lower()
    for prefix, centre_id in _RESEARCH_CENTRE_URL_PREFIX_TO_ID.items():
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return centre_id
    return None


def _derive_centre_name(centre_id: str, title: str) -> str:
    rule = next((c for c in RESEARCH_DIRECTORATE_CENTRES if c["id"] == centre_id), None)
    if rule:
        return rule["name"]
    display_name = title.split("|")[0].replace(" - SRMIST", "").strip()
    if display_name and len(display_name) >= 3:
        return display_name
    return centre_id.replace("centre--", "").replace("-", " ").title()


def _upsert_centre_entity(
    kg: KnowledgeGraph,
    centre_id: str,
    title: str,
    campus: str,
    url: str,
) -> None:
    name = _derive_centre_name(centre_id, title)
    attrs = {}
    if centre_id in _RESEARCH_CENTRE_ID_SET:
        attrs["domain"] = "research"
        attrs["cluster"] = "research-centre"
    if centre_id not in kg.entities:
        kg.add_entity(Entity(
            id=centre_id,
            name=name,
            entity_type="centre",
            campus=campus,
            url=url,
            attributes=attrs,
        ))
    else:
        kg.entities[centre_id].url = url
        if attrs:
            kg.entities[centre_id].attributes.update(attrs)


def _upsert_rule_entity(kg: KnowledgeGraph, rule: dict, campus: str, url: str) -> None:
    entity = kg.entities.get(rule["id"])
    attrs = dict(rule.get("attributes", {}))
    if entity is None:
        kg.add_entity(Entity(
            id=rule["id"],
            name=rule["name"],
            entity_type=rule["entity_type"],
            campus=campus,
            url=url,
            attributes=attrs,
        ))
    else:
        entity.url = url
        entity.attributes.update(attrs)
    if rule["id"] != _RESEARCH_DIRECTORATE_ID:
        kg.add_relationship(Relationship(
            source_id=rule["id"],
            target_id=_RESEARCH_DIRECTORATE_ID,
            relation_type="also_listed_under",
        ))
        if rule["id"] == "misc--dr-paarivendhar-research-colloquium":
            kg.add_relationship(Relationship(
                source_id=rule["id"],
                target_id="misc--news-and-events",
                relation_type="also_listed_under",
            ))


def _extract_centre_id_from_link(link: str) -> Optional[str]:
    research_centre_id = _match_research_centre_url(link)
    if research_centre_id:
        return research_centre_id

    m = _CENTRE_RE.match(link)
    if m:
        return _resolve_centre_id(m.group(1))

    m = _DEPT_ROOT_RE.match(link.rstrip("/") + "/")
    if m and _is_centre_slug(m.group(1)):
        return _resolve_centre_id(m.group(1))

    m = _LAB_RE.match(link.rstrip("/") + "/")
    if m:
        return _resolve_centre_id(m.group(1))

    return None


def _attach_centre_to_context(kg: KnowledgeGraph, source_eid: str, centre_eid: str) -> None:
    if source_eid not in kg.entities or centre_eid not in kg.entities:
        return

    source_entity = kg.entities[source_eid]
    existing_primary_parents = [
        r.source_id
        for r in kg.relationships
        if r.target_id == centre_eid and r.relation_type == "has_centre"
    ]
    non_research_primary_parents = [
        parent_id for parent_id in existing_primary_parents
        if parent_id != _RESEARCH_DIRECTORATE_ID
    ]

    if source_eid in existing_primary_parents:
        return

    if source_entity.entity_type == "directorate":
        if source_eid == _RESEARCH_DIRECTORATE_ID:
            if non_research_primary_parents:
                kg.add_relationship(Relationship(
                    source_id=centre_eid,
                    target_id=source_eid,
                    relation_type="also_listed_under",
                ))
                return
            kg.add_relationship(Relationship(
                source_id=source_eid,
                target_id=centre_eid,
                relation_type="has_centre",
            ))
            return

        if existing_primary_parents:
            kg.add_relationship(Relationship(
                source_id=centre_eid,
                target_id=source_eid,
                relation_type="also_listed_under",
            ))
            return
        kg.add_relationship(Relationship(
            source_id=source_eid,
            target_id=centre_eid,
            relation_type="has_centre",
        ))
        if centre_eid in _RESEARCH_CENTRE_ID_SET:
            kg.add_relationship(Relationship(
                source_id=centre_eid,
                target_id=_RESEARCH_DIRECTORATE_ID,
                relation_type="also_listed_under",
            ))
        return

    if not existing_primary_parents:
        kg.add_relationship(Relationship(
            source_id=source_eid,
            target_id=centre_eid,
            relation_type="has_centre",
        ))
        if centre_eid in _RESEARCH_CENTRE_ID_SET:
            kg.add_relationship(Relationship(
                source_id=centre_eid,
                target_id=_RESEARCH_DIRECTORATE_ID,
                relation_type="also_listed_under",
            ))
    else:
        kg.add_relationship(Relationship(
            source_id=centre_eid,
            target_id=source_eid,
            relation_type="also_listed_under",
        ))


def _attach_centre_to_research(kg: KnowledgeGraph, centre_eid: str) -> None:
    _attach_centre_to_context(kg, _RESEARCH_DIRECTORATE_ID, centre_eid)


def _has_non_research_primary_parent(kg: KnowledgeGraph, centre_eid: str) -> bool:
    return any(
        r.target_id == centre_eid
        and r.relation_type == "has_centre"
        and r.source_id != _RESEARCH_DIRECTORATE_ID
        for r in kg.relationships
    )


def _infer_research_cross_links(kg: KnowledgeGraph, pages: list[dict]) -> None:
    """Deprecated broad inference hook kept as a no-op for compatibility."""
    return


def _apply_program_parent_overrides(kg: KnowledgeGraph) -> None:
    """Attach known loose programs to their canonical parent department."""
    kept_relationships = [
        rel for rel in kg.relationships
        if not (
            rel.relation_type == "offers_program"
            and rel.target_id in (set(PROGRAM_PARENT_OVERRIDES) | PROGRAM_DETACHED_IDS)
        )
    ]
    kg.relationships = kept_relationships

    for program_id, parent_id in PROGRAM_PARENT_OVERRIDES.items():
        if program_id not in kg.entities or parent_id not in kg.entities:
            continue
        kg.add_relationship(Relationship(
            source_id=parent_id,
            target_id=program_id,
            relation_type="offers_program",
            metadata={"source": "seed-override"},
        ))


def _apply_centre_parent_overrides(kg: KnowledgeGraph) -> None:
    """Enforce reviewed centre placements and detach outdated loose nodes."""
    detached_or_overridden = set(CENTRE_PARENT_OVERRIDES) | CENTRE_DETACHED_IDS
    kg.relationships = [
        rel for rel in kg.relationships
        if not (
            (
                rel.relation_type == "has_centre"
                and rel.target_id in detached_or_overridden
            )
            or (
                rel.relation_type == "also_listed_under"
                and rel.source_id in detached_or_overridden
            )
        )
    ]

    for centre_id, parent_id in CENTRE_PARENT_OVERRIDES.items():
        if centre_id not in kg.entities or parent_id not in kg.entities:
            continue
        kg.add_relationship(Relationship(
            source_id=parent_id,
            target_id=centre_id,
            relation_type="has_centre",
            metadata={"source": "seed-override"},
        ))


def _apply_orphan_program_inference(kg: KnowledgeGraph) -> None:
    """Link orphaned programs to their best-known parent department."""
    linked_programs = {
        rel.target_id
        for rel in kg.relationships
        if rel.relation_type == "offers_program"
    }
    for entity_id, entity in list(kg.entities.items()):
        if entity.entity_type != "program" or entity_id in linked_programs:
            continue
        parent_id = _infer_program_parent_from_text(entity)
        if not parent_id or parent_id not in kg.entities:
            continue
        kg.add_relationship(Relationship(
            source_id=parent_id,
            target_id=entity_id,
            relation_type="offers_program",
            metadata={"source": "pattern-inference"},
        ))


def _infer_program_parent_from_text(program: Entity) -> Optional[str]:
    text = f"{program.name} {program.url}".lower()
    for pattern, parent_id in PROGRAM_PARENT_PATTERNS:
        if re.search(pattern, text):
            return parent_id
    return None


def _apply_orphan_centre_inference(kg: KnowledgeGraph) -> None:
    """Link orphaned centres/labs to the closest known parent."""
    linked_centres = {
        rel.target_id
        for rel in kg.relationships
        if rel.relation_type == "has_centre"
    }
    for entity_id, entity in list(kg.entities.items()):
        if entity.entity_type != "centre" or entity_id in linked_centres:
            continue
        parent_id = _infer_centre_parent_from_text(entity, kg)
        if not parent_id or parent_id not in kg.entities:
            continue
        kg.add_relationship(Relationship(
            source_id=parent_id,
            target_id=entity_id,
            relation_type="has_centre",
            metadata={"source": "pattern-inference"},
        ))


def _infer_centre_parent_from_text(centre: Entity, kg: KnowledgeGraph) -> Optional[str]:
    if centre.id in CENTRE_PARENT_OVERRIDES:
        return CENTRE_PARENT_OVERRIDES[centre.id]

    match = _DEPT_SUBPAGE_RE.match(centre.url.rstrip("/") + "/")
    if match:
        dept_slug = match.group(1)
        dept_id = f"department--{dept_slug}"
        if dept_id in kg.entities:
            return dept_id
        if dept_slug in CENTRE_URL_PARENT_OVERRIDES:
            return CENTRE_URL_PARENT_OVERRIDES[dept_slug]

    text = f"{centre.name} {centre.url}".lower()
    for pattern, parent_id in CENTRE_PARENT_PATTERNS:
        if re.search(pattern, text):
            return parent_id

    if "/lab/" in centre.url.lower():
        return "directorate--directorate-of-research"
    return None


def _enforce_single_parent(kg: KnowledgeGraph) -> None:
    """Keep a single primary parent for departments/sub-colleges and programs."""
    kept: list[Relationship] = []
    seen_dept_like: set[str] = set()
    seen_programs: set[str] = set()

    for rel in kg.relationships:
        if rel.relation_type in ("has_department", "has_sub_college"):
            if rel.target_id in seen_dept_like:
                continue
            seen_dept_like.add(rel.target_id)
        elif rel.relation_type == "offers_program":
            if rel.target_id in seen_programs:
                continue
            seen_programs.add(rel.target_id)
        kept.append(rel)

    kg.relationships = kept


def _normalize_known_entities(kg: KnowledgeGraph) -> None:
    """Apply deterministic merges for known SRM naming/category duplicates."""
    # 1) School of Law page is the Department of Law under SRM School of Law.
    law_old = "department--school-of-law"
    law_new = "department--department-of-law"
    if law_old in kg.entities:
        _merge_entity_into(
            kg,
            old_id=law_old,
            new_id=law_new,
            new_name="Department of Law",
            new_type="department",
        )
    elif law_new not in kg.entities:
        kg.add_entity(Entity(
            id=law_new,
            name="Department of Law",
            entity_type="department",
            campus="KTR",
            url="",
            attributes={},
        ))

    if law_new in kg.entities:
        kg.add_relationship(Relationship(
            source_id="college--srm-school-of-law",
            target_id=law_new,
            relation_type="has_department",
        ))
        # Move program ownership from law college to Department of Law.
        to_move = [
            r for r in kg.relationships
            if r.source_id == "college--srm-school-of-law"
            and r.relation_type == "offers_program"
        ]
        for rel in to_move:
            kg.add_relationship(Relationship(
                source_id=law_new,
                target_id=rel.target_id,
                relation_type="offers_program",
                metadata=dict(rel.metadata or {}),
            ))
        kg.relationships = [
            r for r in kg.relationships
            if not (
                r.source_id == "college--srm-school-of-law"
                and r.relation_type == "offers_program"
            )
        ]

    # 2) School of Teacher Education and Research == School of Education dept.
    _merge_entity_into(
        kg,
        old_id="school--school-of-teacher-education-and-research",
        new_id="department--school-of-education",
        new_name="School of Education",
        new_type="department",
    )
    if "department--school-of-education" in kg.entities:
        kg.add_relationship(Relationship(
            source_id=_CSH,
            target_id="department--school-of-education",
            relation_type="has_department",
        ))

    _merge_entity_into(
        kg,
        old_id="school--school-of-bioengineering",
        new_id="school--school-of-bio-engineering",
        new_name="School of Bio-Engineering",
        new_type="school",
    )

    # 3) Directorate of Entrepreneurship and Innovation should be a directorate.
    _merge_entity_into(
        kg,
        old_id="department--directorate-of-entrepreneurship-and-innovation",
        new_id="directorate--directorate-of-entrepreneurship-and-innovation",
        new_name="Directorate of Entrepreneurship and Innovation",
        new_type="directorate",
    )
    if "directorate--directorate-of-entrepreneurship-and-innovation" in kg.entities:
        kg.add_relationship(Relationship(
            source_id="campus--kattankulathur",
            target_id="directorate--directorate-of-entrepreneurship-and-innovation",
            relation_type="has_directorate",
        ))

    # 4) Duplicate centre/page normalizations from manual review.
    # #3 merge
    _merge_entity_into(
        kg,
        old_id="centre--center-of-excellence-for-electronic-cooling-and-cfd-simulation",
        new_id="centre--coe-electronic-cooling-cfd",
        new_name="Center of Excellence for Electronic Cooling and CFD Simulation",
        new_type="centre",
    )
    # #4 merge
    _merge_entity_into(
        kg,
        old_id="centre--center-of-excellence-in-materials-for-advanced-technologies-cemat",
        new_id="centre--cemat",
        new_name="Center of Excellence in Materials for Advanced Technologies (CeMAT)",
        new_type="centre",
    )
    # #5 merge
    _merge_entity_into(
        kg,
        old_id="centre--centre-for-analysis-of-movement-ergonomics-research-and-animersion",
        new_id="centre--camera",
        new_name="Centre for Analysis of Movement, Ergonomics Research and Animersion",
        new_type="centre",
    )
    # #6 merge with both URLs retained
    _merge_entity_into(
        kg,
        old_id="centre--cem",
        new_id="centre--centre-for-electric-mobility",
        new_name="Centre for Electric Mobility",
        new_type="centre",
    )
    # #7 merge with both URLs retained
    _merge_entity_into(
        kg,
        old_id="centre--computational-laboratory",
        new_id="centre--computational-laboratory-aero",
        new_name="Computational Laboratory",
        new_type="centre",
    )
    # #9 remove consultancy/collaboration info-only nodes
    _drop_entity(kg, "centre--consultancy-and-collaboration")
    _drop_entity(kg, "centre--consultancy-collaboration")
    # #10 merge
    _merge_entity_into(
        kg,
        old_id="centre--dr-t-r-paarivendhar-multidisciplinary-research-centre",
        new_id="centre--dr-trp-multidisciplinary-research-centre",
        new_name="Dr. T. R. Paarivendhar Multidisciplinary Research Centre",
        new_type="centre",
    )


def _merge_entity_into(
    kg: KnowledgeGraph,
    old_id: str,
    new_id: str,
    new_name: str,
    new_type: str,
) -> None:
    """Merge old_id into new_id, preserving URLs/attributes and rewiring links."""
    old_entity = kg.entities.get(old_id)
    new_entity = kg.entities.get(new_id)

    if not old_entity and not new_entity:
        return

    if not new_entity:
        seed = old_entity
        kg.add_entity(Entity(
            id=new_id,
            name=new_name,
            entity_type=new_type,
            campus=(seed.campus if seed else "KTR"),
            url=(seed.url if seed else ""),
            attributes=dict(seed.attributes) if seed else {},
        ))
        new_entity = kg.entities[new_id]
    else:
        new_entity.name = new_name
        new_entity.entity_type = new_type

    if old_entity:
        if new_entity.url and old_entity.url and new_entity.url != old_entity.url:
            alts = new_entity.attributes.get("alternate_urls", [])
            if not isinstance(alts, list):
                alts = [str(alts)]
            for u in (new_entity.url, old_entity.url):
                if u and u not in alts:
                    alts.append(u)
            new_entity.attributes["alternate_urls"] = alts
        elif not new_entity.url and old_entity.url:
            new_entity.url = old_entity.url
    if old_entity:
        new_entity.attributes.update(old_entity.attributes or {})

    if old_id == new_id or old_id not in kg.entities:
        return

    rewired: list[Relationship] = []
    for rel in kg.relationships:
        src = new_id if rel.source_id == old_id else rel.source_id
        tgt = new_id if rel.target_id == old_id else rel.target_id
        if src == tgt:
            continue
        rewired.append(Relationship(
            source_id=src,
            target_id=tgt,
            relation_type=rel.relation_type,
            metadata=dict(rel.metadata or {}),
        ))
    kg.relationships = rewired
    del kg.entities[old_id]


def _drop_entity(kg: KnowledgeGraph, entity_id: str) -> None:
    """Remove an entity and all relationships touching it."""
    if entity_id not in kg.entities:
        return
    del kg.entities[entity_id]
    kg.relationships = [
        r for r in kg.relationships
        if r.source_id != entity_id and r.target_id != entity_id
    ]


def _backfill_entity_urls(kg: KnowledgeGraph, pages: list[dict]) -> None:
    for entity_id, override_url in _ENTITY_URL_OVERRIDES.items():
        ent = kg.entities.get(entity_id)
        if ent:
            ent.url = override_url


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
