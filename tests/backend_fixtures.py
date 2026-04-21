from __future__ import annotations

from backend.knowledge_graph import Entity, KnowledgeGraph, Relationship


def build_test_kg() -> KnowledgeGraph:
    kg = KnowledgeGraph()

    entities = [
        Entity(
            id="admission--india--engineering",
            name="Admissions - India - Engineering",
            entity_type="admission",
            campus="KTR",
            url="https://www.srmist.edu.in/admission-india/engineering/",
            attributes={"route": "india", "scope": "faculty", "scope_slug": "engineering"},
        ),
        Entity(
            id="admission--india--medicine-health-sciences",
            name="Admissions - India - Medicine & Health Sciences",
            entity_type="admission",
            campus="KTR",
            url="https://www.srmist.edu.in/admission-india/medicine-health-sciences/",
            attributes={"route": "india", "scope": "faculty", "scope_slug": "medicine-health-sciences"},
        ),
        Entity(
            id="college--faculty-of-engineering-and-technology",
            name="Faculty of Engineering & Technology",
            entity_type="college",
            campus="KTR",
        ),
        Entity(
            id="department--computer-science-and-engineering",
            name="Computer Science and Engineering",
            entity_type="department",
            campus="KTR",
        ),
        Entity(
            id="department--electronics-and-communication-engineering",
            name="Electronics and Communication Engineering",
            entity_type="department",
            campus="KTR",
        ),
        Entity(
            id="program--b-tech-computer-science-and-engineering",
            name="B.Tech Computer Science Engineering 2026",
            entity_type="program",
            campus="KTR",
        ),
        Entity(
            id="program--b-tech-cse-ai-and-machine-learning",
            name="B.Tech CSE AI and Machine Learning 2026",
            entity_type="program",
            campus="KTR",
        ),
        Entity(
            id="program--mba-business-administration",
            name="MBA Business Administration",
            entity_type="program",
            campus="KTR",
        ),
        Entity(
            id="program--b-sc-nursing",
            name="B.Sc Nursing",
            entity_type="program",
            campus="KTR",
        ),
        Entity(
            id="program--b-pharm-pharmacy",
            name="B.Pharm Pharmacy",
            entity_type="program",
            campus="KTR",
        ),
        Entity(
            id="program--pharm-d",
            name="Pharm D Doctor of Pharmacy",
            entity_type="program",
            campus="KTR",
        ),
    ]
    for entity in entities:
        kg.add_entity(entity)

    relationships = [
        Relationship(
            source_id="college--faculty-of-engineering-and-technology",
            target_id="department--computer-science-and-engineering",
            relation_type="has_department",
        ),
        Relationship(
            source_id="college--faculty-of-engineering-and-technology",
            target_id="department--electronics-and-communication-engineering",
            relation_type="has_department",
        ),
        Relationship(
            source_id="department--computer-science-and-engineering",
            target_id="program--b-tech-computer-science-and-engineering",
            relation_type="offers_program",
        ),
        Relationship(
            source_id="department--computer-science-and-engineering",
            target_id="program--b-tech-cse-ai-and-machine-learning",
            relation_type="offers_program",
        ),
        Relationship(
            source_id="admission--india--engineering",
            target_id="program--b-tech-computer-science-and-engineering",
            relation_type="admission_governs",
        ),
        Relationship(
            source_id="admission--india--engineering",
            target_id="program--b-tech-cse-ai-and-machine-learning",
            relation_type="admission_governs",
        ),
        Relationship(
            source_id="admission--india--medicine-health-sciences",
            target_id="program--b-sc-nursing",
            relation_type="admission_governs",
        ),
        Relationship(
            source_id="admission--india--medicine-health-sciences",
            target_id="program--b-pharm-pharmacy",
            relation_type="admission_governs",
        ),
        Relationship(
            source_id="admission--india--medicine-health-sciences",
            target_id="program--pharm-d",
            relation_type="admission_governs",
        ),
    ]
    for relationship in relationships:
        kg.add_relationship(relationship)

    return kg


def build_test_admission_profiles() -> dict[str, dict]:
    return {
        "admission--india--engineering": {
            "admission_id": "admission--india--engineering",
            "name": "Admissions - India - Engineering",
            "route": "india",
            "scope": "faculty",
            "source_url": "https://www.srmist.edu.in/admission-india/engineering/",
            "criteria": {
                "text": "Admissions to B.Tech programmes are routed through the official engineering admission process.",
                "last_scraped_at": "2026-04-12",
            },
            "eligibility": {
                "text": "Candidate should have passed the qualifying examination with Physics, Chemistry and Mathematics.",
                "last_scraped_at": "2026-04-12",
            },
            "fees": {"text": "", "last_scraped_at": "2026-04-12"},
            "how_to_apply": {
                "text": "Legacy content mentioned SMAT Round 1, Round 2 and PI/GD, but that route is not valid for this programme.",
                "last_scraped_at": "2026-04-12",
            },
            "important_dates": {
                "text": "Check the official B.Tech application portal for the latest phase-wise schedule.",
                "last_scraped_at": "2026-04-12",
            },
            "apply_links": [
                {
                    "label": "B.Tech Application Form",
                    "url": "https://applications.srmist.edu.in/btech",
                }
            ],
            "exam_links": [],
            "prospectus_links": [],
            "program_rows": [
                {
                    "program_id": "program--b-tech-cse-ai-and-machine-learning",
                    "campus": "KTR",
                    "degree": "B.Tech",
                    "specialization": "Computer Science and Engineering with specialization in Artificial Intelligence and Machine Learning",
                    "annual_fees": "475000",
                    "dept": "Computer Science and Engineering",
                    "program_level": "Under Graduate",
                    "program_type": "Full Time",
                    "eligibility_override": "",
                    "apply_url": "https://applications.srmist.edu.in/btech",
                    "route_family": "srmjeee_ug",
                    "verification_status": "verified",
                    "raw_route_tokens": ["srmjeee_ug"],
                    "route_notes": "",
                    "exam": "SRMJEEE (UG)",
                    "source_url": "https://www.srmist.edu.in/admission-india/engineering/",
                    "last_scraped_at": "2026-04-12",
                    "source_type": "main_site",
                    "match_confidence": 0.98,
                    "match_method": "fixture",
                }
            ],
        },
        "admission--india--medicine-health-sciences": {
            "admission_id": "admission--india--medicine-health-sciences",
            "name": "Admissions - India - Medicine & Health Sciences",
            "route": "india",
            "scope": "faculty",
            "source_url": "https://www.srmist.edu.in/admission-india/medicine-health-sciences/",
            "criteria": {
                "text": "Health sciences admissions follow the official programme-specific entrance route published by SRMIST.",
                "last_scraped_at": "2026-04-12",
            },
            "eligibility": {
                "text": "Candidate should satisfy the published subject and marks requirements for the selected programme.",
                "last_scraped_at": "2026-04-12",
            },
            "fees": {"text": "", "last_scraped_at": "2026-04-12"},
            "how_to_apply": {
                "text": "Some legacy summaries incorrectly mention CET registration and the Post Basic Diploma Operation Room Nursing path.",
                "last_scraped_at": "2026-04-12",
            },
            "important_dates": {
                "text": "Refer to the health sciences application portal for the latest admissions timeline.",
                "last_scraped_at": "2026-04-12",
            },
            "apply_links": [
                {
                    "label": "Health Sciences Application Form",
                    "url": "https://applications.srmist.edu.in/srmhs",
                }
            ],
            "exam_links": [],
            "prospectus_links": [],
            "program_rows": [
                {
                    "program_id": "program--b-sc-nursing",
                    "campus": "KTR",
                    "degree": "B.Sc",
                    "specialization": "Nursing",
                    "annual_fees": "100000",
                    "dept": "Nursing",
                    "program_level": "Under Graduate",
                    "program_type": "Full Time",
                    "eligibility_override": "",
                    "apply_url": "https://applications.srmist.edu.in/srmhs",
                    "route_family": "srmjeeh_ug",
                    "verification_status": "conflict",
                    "raw_route_tokens": ["srmjeeh_ug", "srmjeen_ug"],
                    "route_notes": "Conflicting route labels found: srmjeeh_ug, srmjeen_ug.",
                    "exam": "",
                    "source_url": "https://www.srmist.edu.in/admission-india/medicine-health-sciences/",
                    "last_scraped_at": "2026-04-12",
                    "source_type": "main_site",
                    "match_confidence": 0.97,
                    "match_method": "fixture",
                },
                {
                    "program_id": "program--b-pharm-pharmacy",
                    "campus": "KTR",
                    "degree": "B.Pharm",
                    "specialization": "Pharmacy",
                    "annual_fees": "175000",
                    "dept": "Pharmacy",
                    "program_level": "Under Graduate",
                    "program_type": "Full Time",
                    "eligibility_override": "",
                    "apply_url": "https://applications.srmist.edu.in/srmhs",
                    "route_family": "srmjeeh_ug",
                    "verification_status": "conflict",
                    "raw_route_tokens": ["srmjeeh_ug", "srmjeen_ug"],
                    "route_notes": "Conflicting route labels found: srmjeeh_ug, srmjeen_ug.",
                    "exam": "",
                    "source_url": "https://www.srmist.edu.in/admission-india/medicine-health-sciences/",
                    "last_scraped_at": "2026-04-12",
                    "source_type": "main_site",
                    "match_confidence": 0.97,
                    "match_method": "fixture",
                },
                {
                    "program_id": "program--pharm-d",
                    "campus": "KTR",
                    "degree": "Pharm D",
                    "specialization": "Doctor of Pharmacy",
                    "annual_fees": "225000",
                    "dept": "Pharmacy",
                    "program_level": "Under Graduate",
                    "program_type": "Full Time",
                    "eligibility_override": "",
                    "apply_url": "https://applications.srmist.edu.in/srmhs",
                    "route_family": "srmjeeh_ug",
                    "verification_status": "conflict",
                    "raw_route_tokens": ["srmjeeh_ug", "srmjeen_ug"],
                    "route_notes": "Conflicting route labels found: srmjeeh_ug, srmjeen_ug.",
                    "exam": "",
                    "source_url": "https://www.srmist.edu.in/admission-india/medicine-health-sciences/",
                    "last_scraped_at": "2026-04-12",
                    "source_type": "main_site",
                    "match_confidence": 0.97,
                    "match_method": "fixture",
                },
            ],
        },
    }
