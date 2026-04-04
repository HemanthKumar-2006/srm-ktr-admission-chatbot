"""Analyze knowledge graph for duplicates and issues."""
import json
from collections import Counter, defaultdict

with open(r'vector_db_qdrant\knowledge_graph.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

entities = data['entities']
rels = data['relationships']

print(f'Total entities: {len(entities)}')
print(f'Total relationships: {len(rels)}')
print()

type_counts = Counter(e['entity_type'] for e in entities.values())
for t, c in sorted(type_counts.items()):
    print(f'  {t}: {c}')

print()
print('=== DUPLICATE NAMES ===')
name_groups = defaultdict(list)
for eid, e in entities.items():
    name_groups[e['name'].lower().strip()].append(eid)
for name, eids in sorted(name_groups.items()):
    if len(eids) > 1:
        print(f'DUPLICATE NAME: "{name}"')
        for eid in eids:
            print(f'  -> {eid} (type={entities[eid]["entity_type"]})')

print()
print('=== ALL COLLEGE ENTITIES ===')
for eid, e in entities.items():
    if e['entity_type'] == 'college':
        print(f'  {eid}: "{e["name"]}" url={e["url"]}')

print()
print('=== ADMISSION RELATIONSHIPS ===')
for r in rels:
    if 'admission' in r['source_id'] or 'admission' in r['target_id']:
        print(f'  {r["source_id"]} --[{r["relation_type"]}]--> {r["target_id"]}')

print()
print('=== COLLABORATES_WITH ===')
for r in rels:
    if r['relation_type'] == 'collaborates_with':
        print(f'  {r["source_id"]} --[collaborates_with]--> {r["target_id"]}')

print()
print('=== CENTRES TYPED AS DEPARTMENT ===')
for eid, e in entities.items():
    if ('centre' in e['name'].lower() or 'center' in e['name'].lower() or 'cdc' in eid.lower()) and e['entity_type'] != 'centre':
        print(f'  {eid}: "{e["name"]}" type={e["entity_type"]}')

print()
print('=== DEPARTMENTS WITH MULTIPLE PARENTS ===')
dept_parents = defaultdict(list)
for r in rels:
    if r['relation_type'] in ('has_department', 'has_centre'):
        dept_parents[r['target_id']].append((r['source_id'], r['relation_type']))
for tid, parents in sorted(dept_parents.items()):
    if len(parents) > 1:
        print(f'MULTI-PARENT: {tid}')
        for src, rel in parents:
            print(f'  <- {src} ({rel})')

print()
print('=== PROGRAMS WITH MULTIPLE PARENTS ===')
prog_parents = defaultdict(list)
for r in rels:
    if r['relation_type'] == 'offers_program':
        prog_parents[r['target_id']].append(r['source_id'])
for tid, parents in sorted(prog_parents.items()):
    if len(parents) > 1:
        print(f'MULTI-PARENT: {tid} "{entities.get(tid, {}).get("name", "?")}"')
        for src in parents:
            print(f'  <- {src}')

print()
print('=== MISTYPED ENTITIES (not real departments) ===')
for eid, e in entities.items():
    if e['entity_type'] == 'department':
        name = e['name'].lower()
        if any(kw in name for kw in ['achievements', 'publications', 'research 2', 'librarian', 'som', 'cesd']):
            print(f'  SUSPICIOUS: {eid}: "{e["name"]}"')
        if any(kw in eid for kw in ['--cdc-', '--cet-cdc', '--achievements', '--publications-20', '--research-2', '--research', '--librarian', '--som', '--cesd']):
            print(f'  SUSPICIOUS ID: {eid}: "{e["name"]}"')
