from __future__ import annotations

from backend.knowledge_graph import Entity, KnowledgeGraph, Relationship


def build_test_kg() -> KnowledgeGraph:
    kg = KnowledgeGraph()

    entities = [
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
    ]
    for relationship in relationships:
        kg.add_relationship(relationship)

    return kg
