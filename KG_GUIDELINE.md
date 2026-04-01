# SRMIST Knowledge Graph — Construction Guideline

> **Version:** 1.1  
> **Last Updated:** 2026-04-01  
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
| `college` | 🔴 | A Faculty / College at the top of a campus's academic structure. Despite some being called "School" (e.g., SRM School of Law), they still use the `college` type. | Faculty of Engineering & Technology |
| `school` | 🟥 | An intermediate grouping of departments *within* a college (e.g., under FET) | School of Computing |
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
| `has_centre` | college / department / directorate → centre | Has a research/service centre |
| `has_directorate` | campus → directorate | Campus has an administrative directorate |
| `has_facility` | campus → facility | Campus has a physical facility |
| `offers_program` | department → program | Department offers a degree program |
| `has_admission` | university / campus → admission | University/campus has an admission node |
| `admission_governs` | admission → program | Admission portal governs a program's intake |
| `collaborates_with` | centre / program / event / lab ↔ centre / program / event / lab | Collaboration only between lower-order entities |
| `also_listed_under` | centre / facility / misc / publication → directorate / section / college / department | Cross-listing when a node is discoverable from multiple contexts but should keep one canonical home |
| `belongs_to` | department / centre → college | Reverse of has_department / has_centre (for lookup) |

### Rules

- Relationships are **directed**. The source is always the "parent" or "owner" unless noted.
- `also_listed_under` must **never** replace the primary `has_*` link. Always add both.
- Do not create `has_department` from `university` or `campus` directly — always go through a `college`.
- `admission_governs` links an `admission` node to specific `program` nodes (not to departments).
- Do not create `collaborates_with` between `directorate`, `college`, or `department`.
- If two higher-order entities are connected through a shared centre, lab, event, or program, that collaboration is **derived**, not stored as a direct edge.

---

## 4. Canonical SRMIST Hierarchy

```
SRMIST (university)
├── Kattankulathur (campus)
│   ├── [Academics]
│   │   ├── Faculty of Engineering & Technology (college)
│   │   │   ├── School of Computing (school)
│   │   │   │   └── 4 Departments (department)
│   │   │   ├── School of Bio-Engineering (school)
│   │   │   │   └── 5 Departments (department)
│   │   │   ├── School of Electrical and Electronics Engineering (school)
│   │   │   │   └── 3 Departments (department)
│   │   │   ├── School of Mechanical Engineering (school)
│   │   │   │   └── 4 Departments (department)
│   │   │   ├── School of Civil Engineering (school)
│   │   │   │   └── 1 Department (department)
│   │   │   ├── School of Architecture & Interior Design (school & department)
│   │   │   ├── School of Basic Sciences (school)
│   │   │   │   └── 4 Departments (department)
│   │   │   └── 17 Centres (centre)
│   │   │       ├── CDC-CET (career development centre) ← also linked to Directorate of Career Centre
│   │   │       ├── Dept-level centres (e.g., Centre for AI under Comp Intel)
│   │   │       └── Research Centres
│   │   ├── Faculty of Science & Humanities (college)
│   │   │   ├── 22 Departments (department)
│   │   │   └── CDC-CSH (centre) ← also linked to Directorate of Career Centre
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
│   │   │   ├── CDC-CET (centre) ← co-linked to FET
│   │   │   └── CDC-CSH (centre) ← co-linked to CSH
│   │   ├── ITKM (directorate)
│   │   ├── Directorate of Learning and Development (directorate)
│   │   ├── Directorate of Campus Administration & Facilities (directorate)
│   │   ├── Directorate of Distance Education (directorate)
│   │   └── Directorate of Online Education (directorate)
│   │
│   ├── [Facilities]
│   │   ├── Housing (facility)  ← also_listed_under Campus Life
│   │   ├── Transport (facility)  ← also_listed_under Campus Life
│   │   ├── SRM Hotels (facility)
│   │   └── Library (facility)
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
├── [Admissions]
│   ├── Admissions — India (admission)
│   └── Admissions — International (admission)
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
10. Rule-based overrides for structurally inconsistent sections such as Directorate of Research

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
- Canonical ownership rules for Directorate of Research centres

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

### Directorate of Research Override

The SRMIST website mixes Research content across `/research/`, `/department/`, event pages, and college pages. To keep rebuilds stable:

- The following are treated as the **core centres associated with Directorate of Research**:
  - IIISM, REACH, NRC, CACR, SRM-DBT Platform, Medical Research Centre (aMRC), Centre for Statistics, EQRC/ERC, HPCC, SCIF
- If one of the above centres is explicitly listed under a college or department, that academic unit should be the **primary** parent via `has_centre`.
- In that case, Directorate of Research must become the **secondary** parent via `also_listed_under`.
- If a centre appears only in Research context and no academic owner is known, Directorate of Research may remain the primary `has_centre` parent.
- Add `also_listed_under` for every additional surfaced context that matters beyond the primary owner.
- Do not add direct `collaborates_with` edges from Directorate of Research to colleges or departments. Any such relationship must be inferred from shared lower-order entities.
- Research governance and archive pages such as R&D Cell, University Research Council, Projects, Sponsored Projects, SERI, Publications, Patents, Ph.D Awarded, and DPRC must map to stable canonical entities even if their URLs are not under `/directorate/`.
- DPRC should also be cross-linked to the general Events / News context.

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
3. If the directorate is surfaced from another page context, use `also_listed_under` where needed.
4. Do not add direct `collaborates_with` links from a directorate to a college or department.

### Adding or Reclassifying a Research Centre
1. If it is one of the institution-level research wings/centres, add it to the Research override list in `knowledge_graph.py`.
2. If the centre is explicitly owned by a college or department on the site, keep that academic parent as the primary `has_centre` owner.
3. Add Directorate of Research as `also_listed_under` for the same centre.
4. Add slug aliases if the site uses abbreviations, alternate spellings, or department-style URLs.

### Modeling Collaboration
1. Use `collaborates_with` only between lower-order entities such as centres, labs, events, and programs.
2. Never add `collaborates_with` directly between `directorate`, `college`, or `department`.
3. Represent higher-order collaboration by linking both higher-order entities to the same lower-order node.
4. Any higher-order collaboration report should be derived from shared lower-order nodes, not persisted in the KG.

### Adding a Research Section Page
1. Map the page to a stable canonical node in the Research override rules.
2. Use the closest existing entity type (`misc` or `publication`) rather than inventing a duplicate node from each URL variant.
3. Attach it to Directorate of Research via `also_listed_under`.

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
