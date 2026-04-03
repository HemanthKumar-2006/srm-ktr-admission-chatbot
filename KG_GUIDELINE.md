# SRMIST Knowledge Graph — Construction Guideline

> **Version:** 1.0  
> **Last Updated:** 2026-03-31  
> **Purpose:** Canonical reference for building, maintaining, and extending the SRMIST Knowledge Graph.

This document is the **single source of truth** for the KG schema. Any automated builder,
manual editor, or ingestion script must follow the rules defined here.

---

## Table of Contents

1. [Terminology](#1-terminology)
2. [Entity Types](#2-entity-types)
3. [Relation Types](#3-relation-types)
4. [Canonical SRMIST Hierarchy](#4-canonical-srmist-hierarchy)
5. [Naming Conventions](#5-naming-conventions)
6. [Seeded (Hardcoded) Data](#6-seeded-hardcoded-data)
7. [Dynamic (Scraped) Data](#7-dynamic-scraped-data)
8. [Cross-Link Rules](#8-cross-link-rules)
9. [Update Rules](#9-update-rules)
10. [Future: Visual KG Editor](#10-future-visual-kg-editor)

---

## 1. Terminology

| Term | Meaning |
|---|---|
| **Entity** | A node in the graph representing a real-world SRMIST concept |
| **Relationship** | A directed link between two entities |
| **Seed data** | Hardcoded entities/relationships that form the stable skeleton of the graph |
| **Dynamic data** | Entities and relationships discovered by scraping the SRMIST website |
| **Cross-link** | A relationship that connects an entity to more than one parent (e.g., Housing appears under both Facilities and Campus Life) |
| **Slug** | URL-safe identifier derived from a name, e.g., `faculty-of-engineering-technology` |

---

## 2. Entity Types

Every entity must have exactly one `entity_type` from the table below.

| Type | Tag | Description | Example |
|---|---|---|---|
| `university` | 🟣 | Top-level institution root. There is only **one** university node. | SRMIST |
| `campus` | 🟠 | A physical campus of SRMIST. | Kattankulathur |
| `college` | 🔴 | A Faculty / College / School at the top of a campus's academic structure. Despite some being called "School" (e.g., SRM School of Law), they still use the `college` type. | Faculty of Engineering & Technology |
| `sub_college` | 🩷 | A college **within** the Medicine & Health Sciences college only. | College of Dentistry |
| `department` | 🟢 | A Department or Centre-of-study under a college or sub-college. | Dept of Computer Science |
| `centre` | 🩵 | A research or service centre. May be cross-linked to multiple parents (college + directorate). | CACR |
| `directorate` | 🟡 | An administrative directorate or division at campus level. | Directorate of Research |
| `program` | 🟡 | A degree / course offered by a department. | B.Tech Computer Science |
| `facility` | 🟢 | A physical / operational campus service. NOT academic. | Housing, Transport, SRM Hotels |
| `admission` | 🔵 | An admission process portal (India or International). | Admissions — India |
| `publication` | 🟣 | Publications, achievements, or faculty gateway sections. | Publications |
| `misc` | ⚫ | Utility / informational pages that do not fit above categories. | News & Events, Blog, About |

### Rules

- A node's `entity_type` must **never** change once assigned. To reclassify, remove and recreate.
- `sub_college` is **only** used for the 7 immediate children of Medicine & Health Sciences.
- Directorates like "Directorate of Career Centre" are `directorate`, **not** `facility`.
- "Career Development Centres" inside departments (linked to Career Centre directorate) are `centre`.
- `misc` is a catch-all — use it sparingly.

---

## 3. Relation Types

Every relationship must have a `relation_type` from this table.

| Relation | Direction | Description |
|---|---|---|
| `has_campus` | university → campus | SRMIST has a campus |
| `has_college` | campus → college | A campus has a college/faculty |
| `has_sub_college` | college → sub_college | Medicine has sub-colleges |
| `has_department` | college / sub_college / directorate → department | Has a department |
| `has_centre` | college / directorate → centre | Has a research/service centre |
| `has_directorate` | campus → directorate | Campus has an administrative directorate |
| `has_facility` | campus → facility | Campus has a physical facility |
| `offers_program` | department → program | Department offers a degree program |
| `has_admission` | university / campus → admission | University/campus has an admission node |
| `admission_governs` | admission → program | Admission portal governs a program's intake |
| `collaborates_with` | directorate ↔ college / centre | Shared research or operational collaboration |
| `also_listed_under` | facility / centre → directorate / section | Cross-listing when a node logically belongs to 2+ parents |
| `belongs_to` | department / centre → college | Reverse of has_department / has_centre (for lookup) |

### Rules

- Relationships are **directed**. The source is always the "parent" or "owner" unless noted (collaborates_with is bidirectional).
- `also_listed_under` must **never** replace the primary `has_*` link. Always add both.
- Do not create `has_department` from `university` or `campus` directly — always go through a `college`.
- `admission_governs` links an `admission` node to specific `program` nodes (not to departments).

---

## 4. Canonical SRMIST Hierarchy

```
SRMIST (university)
├── Kattankulathur (campus)
│   ├── [Academics]
│   │   ├── Faculty of Engineering & Technology (college)
│   │   │   ├── 22 Departments (department)
│   │   │   │   └── Programs (program)
│   │   │   └── 17 Centres (centre)  ← some also cross-linked to Directorate of Research
│   │   ├── Faculty of Science & Humanities (college)
│   │   │   ├── 22 Departments (department)
│   │   │   └── 1 Centre (centre)
│   │   ├── Medicine & Health Sciences (college)
│   │   │   ├── College of Medicine (sub_college)
│   │   │   ├── College of Dentistry (sub_college)
│   │   │   ├── College of Pharmacy (sub_college)
│   │   │   ├── College of Physiotherapy (sub_college)
│   │   │   ├── College of Occupational Therapy (sub_college)
│   │   │   ├── College of Nursing (sub_college)
│   │   │   └── School of Public Health (sub_college)
│   │   │       └── [each sub_college has its own departments]
│   │   ├── College of Agricultural Sciences (college)
│   │   │   └── 19 Departments (department)
│   │   ├── SRM School of Law (college)
│   │   │   └── Department of Law (department)  ← college and dept are effectively the same
│   │   └── Faculty of Management (college)
│   │       └── Department of Management (department)
│   │
│   ├── [Directorates]
│   │   ├── Directorate of Research (directorate)
│   │   │   └── Research Centres (centre) ← also cross-linked to colleges
│   │   ├── Controller of Examinations (directorate)
│   │   │   └── [also_listed_under Admissions — India]
│   │   ├── Directorate of Alumni Affairs (directorate)
│   │   ├── Directorate of Communications (directorate)
│   │   ├── Directorate of Career Centre (directorate)
│   │   │   └── Career Development Centres (centre) ← also in departments
│   │   ├── ITKM (directorate)
│   │   ├── Directorate of Learning and Development (directorate)
│   │   ├── Directorate of Campus Administration & Facilities (directorate)
│   │   ├── Directorate of Distance Education (directorate)
│   │   └── Directorate of Online Education (directorate)
│   │
│   ├── [Facilities]
│   │   ├── Housing (facility)  ← also_listed_under Campus Life
│   │   │   ├── Boys Hostel
│   │   │   ├── Girls Hostel
│   │   │   └── International Hostel  ← also_listed_under International Students
│   │   ├── Transport (facility)  ← also_listed_under Campus Life
│   │   ├── SRM Hotels (facility)
│   │   └── Library (facility)
│   │
│   ├── [Admissions]
│   │   ├── Admissions — India (admission)
│   │   └── Admissions — International (admission)
│   │
│   └── [Misc]
│       ├── Publications (publication)
│       ├── Faculty Achievements (publication)
│       ├── News & Events (misc)
│       ├── Blog (misc)
│       ├── Careers at SRM (misc)
│       ├── About SRMIST (misc)
│       └── Contact (misc)
│
├── Ramapuram (campus)
│   └── [similar structure, populate from scrape]
│
└── Vadapalani (campus)
    └── [similar structure, populate from scrape]
```

---

## 5. Naming Conventions

### Entity Names
- Always spell out the **full official name** — no abbreviations in names.
  - ✅ `Faculty of Engineering & Technology`
  - ❌ `FET`, `Engg & Tech`
- Use `&` not `and` where the official name uses `&`.
- Title-case all entity names.
- Department names must include "Department of" prefix where official.
  - ✅ `Department of Computer Science and Engineering`
  - ❌ `Computer Science`

### Entity IDs (Slugs)
IDs are auto-generated as `{type}--{slug}` where slug is lowercase, spaces → hyphens, & → and, special chars stripped.
- `university--srmist`
- `campus--kattankulathur`
- `college--faculty-of-engineering-and-technology`
- `department--department-of-computer-science-and-engineering`
- `directorate--directorate-of-research`

### Programs
- Include the degree prefix: `B.Tech`, `M.Tech`, `M.B.B.S`, `Ph.D`
- Include specialisation: `B.Tech Computer Science and Engineering`

---

## 6. Seeded (Hardcoded) Data

The following data is defined as constants in `knowledge_graph.py` under `SEED_*` variables. These form the **skeleton** of the graph and are always present regardless of what the scraper finds.

### Why Seed?
- The SRMIST website structure is not consistent enough to reliably auto-discover the top-level hierarchy.
- Seeds ensure the graph is always correct at the macro level.
- Dynamic (scraped) data is layered on top of seeds.

### Seed Categories
1. University root entity
2. Campus entities + `has_campus` links
3. KTR college entities + `has_college` links from KTR
4. Medicine sub-college entities + `has_sub_college` links from Medicine
5. KTR directorate entities + `has_directorate` links from KTR
6. KTR facility entities + `has_facility` links from KTR
7. Admission nodes + `has_admission` links
8. Cross-links (`also_listed_under`)
9. Misc nodes

> ⚠️ When adding a new college, department, or directorate that is **known** to always exist, add it to the seed constants first, then verify it also comes through scraping.

---

## 7. Dynamic (Scraped) Data

The scraper populates:
- **Department entities** from `/department/{slug}/` URLs
- **College entities** from `/college/{slug}/` URLs (merged with seeds by ID)
- **Program entities** from `/program/{slug}/` URLs
- **Centre entities** from `/centre/{slug}/` or `/centers/{slug}/` URLs
- **HODs** from content parsing (`_HOD_PATTERN`)
- **Deans** from content parsing (`_DEAN_PATTERN`)
- **Chairpersons** from content parsing (`_CHAIRPERSON_PATTERN`)
- **Relationships** from `internal_links` metadata of each scraped page

### What Changes Over Time (Dynamic)
- HOD / Dean / Chairperson names
- Program names, fees, eligibility criteria (stored as `program.attributes`)
- New departments or centres being added
- New faculty/staff (not stored in KG — too granular)

### What Almost Never Changes (Stable Seeds)
- University, campuses, top-level colleges
- Medicine sub-colleges
- Core directorates
- Naming conventions

---

## 8. Cross-Link Rules

Cross-links use the `also_listed_under` relation type. They are always **in addition to** the primary `has_*` relationship.

| Entity | Primary Parent (`has_*`) | Also Listed Under |
|---|---|---|
| Housing | campus (via `has_facility`) | Campus Life section |
| Transport | campus (via `has_facility`) | Campus Life section |
| International Hostel | Housing facility | International Students section |
| Research Centres in colleges | college (via `has_centre`) | Directorate of Research |
| Career Development Centres in depts | department (via `has_centre`) | Directorate of Career Centre |
| Controller of Examinations | campus (via `has_directorate`) | Admissions — India node |

> **Rule:** Never remove the primary `has_*` relation when adding an `also_listed_under`. Both must coexist.

---

## 9. Update Rules

### Adding a New Department
1. Check if a seed entry is needed (it shouldn't be — departments are dynamic).
2. Ensure the parent college entity already exists (either seeded or scraped).
3. Add `has_department` from college → department.
4. If the department has a known HOD, set `entity.attributes["hod"]`.
5. Re-run `build_knowledge_graph()` and verify with `verify_kg.py`.

### Adding a New College
1. Add a seed entry in `SEED_KTR_COLLEGES` (or the relevant campus seed list).
2. Add a `has_college` link from the campus seed.
3. If the college has sub-colleges (like Medicine), add them to `SEED_MEDICINE_SUB_COLLEGES`.
4. Re-run ingestion.

### Adding a New Directorate
1. Add it to `SEED_KTR_DIRECTORATES`.
2. Add a `has_directorate` link from the KTR campus seed.
3. If the directorate cross-links to colleges or centres, add the `collaborates_with` or `also_listed_under` entry to `SEED_CROSS_LINKS`.

### Updating HOD / Dean names
- These come from scraped content. Re-run ingestion — the scraper will pick up the updated name from the page.
- If a page is not being scraped, update `entity.attributes["hod"]` directly in `knowledge_graph.json` as a temporary fix.

### Adding New Programs
- Programs are fully dynamic. Re-run ingestion after the program page appears on the website.
- Fees, eligibility, and criteria are stored in `program.attributes["fees"]`, `program.attributes["eligibility"]`, `program.attributes["criteria"]`.

---

## 10. Future: Visual KG Editor

> 📌 **Planned — Not yet implemented**

Because the SRMIST website structure is not consistently machine-readable, an automated scraper alone cannot always produce a correct graph. A visual editor will be built to address this:

### Planned Features
- Drag-and-drop node creation and linking
- Node type selector (all 12 entity types with color coding)
- Relation type picker with validation (e.g., prevent `has_college` from a `department`)
- Edit entity attributes (name, HOD, dean, fees, eligibility)
- Import/export of `knowledge_graph.json`
- Diff view to compare auto-built vs manually edited graph
- Audit log of all manual changes

### Design Principles
- Manual edits take **priority** over auto-built links
- The builder must respect a `manual_override: true` flag on entities/relations
- The visual editor should be a standalone web app (built on top of `viz.html`)
