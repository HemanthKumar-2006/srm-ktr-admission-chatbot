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
print('=== INVALID HIGHER-ORDER COLLABORATION EDGES ===')
higher_order_types = {'directorate', 'college', 'department'}
invalid_collabs = []
for r in rels:
    if r['relation_type'] != 'collaborates_with':
        continue
    src_type = entities.get(r['source_id'], {}).get('entity_type')
    tgt_type = entities.get(r['target_id'], {}).get('entity_type')
    if src_type in higher_order_types or tgt_type in higher_order_types:
        invalid_collabs.append((r['source_id'], src_type, r['target_id'], tgt_type))

if not invalid_collabs:
    print('  none')
else:
    for src_id, src_type, tgt_id, tgt_type in invalid_collabs:
        print(f'  INVALID: {src_id} ({src_type}) --[collaborates_with]--> {tgt_id} ({tgt_type})')

print()
print('=== DERIVED HIGHER-ORDER COLLABORATION VIA SHARED LOWER-ORDER ENTITIES ===')
lower_order_types = {'centre', 'program', 'misc'}
shared_map = defaultdict(set)
for eid, entity in entities.items():
    if entity['entity_type'] not in lower_order_types:
        continue

    higher_order_parents = set()
    for r in rels:
        if r['relation_type'] in ('has_centre', 'offers_program') and r['target_id'] == eid:
            src_type = entities.get(r['source_id'], {}).get('entity_type')
            if src_type in higher_order_types:
                higher_order_parents.add(r['source_id'])
        elif r['relation_type'] == 'also_listed_under' and r['source_id'] == eid:
            tgt_type = entities.get(r['target_id'], {}).get('entity_type')
            if tgt_type in higher_order_types:
                higher_order_parents.add(r['target_id'])

    if len(higher_order_parents) < 2:
        continue

    ordered = sorted(higher_order_parents)
    for i, left in enumerate(ordered):
        for right in ordered[i + 1:]:
            shared_map[(left, right)].add(eid)

if not shared_map:
    print('  none')
else:
    for (left, right), shared_children in sorted(shared_map.items()):
        child_names = ', '.join(
            entities[child_id]['name'] for child_id in sorted(shared_children)
        )
        print(f'  {left} <-> {right} via {child_names}')

print()
print('=== CENTRES TYPED AS DEPARTMENT ===')
for eid, e in entities.items():
    if ('centre' in e['name'].lower() or 'center' in e['name'].lower() or 'cdc' in eid.lower()) and e['entity_type'] != 'centre':
        print(f'  {eid}: "{e["name"]}" type={e["entity_type"]}')

print()
print('=== HAS_CENTRE / HAS_DEPARTMENT MULTI-PARENT TARGETS ===')
target_parents = defaultdict(list)
for r in rels:
    if r['relation_type'] in ('has_department', 'has_centre'):
        target_parents[r['target_id']].append((r['source_id'], r['relation_type']))
multi_parent_found = False
for tid, parents in sorted(target_parents.items()):
    if len(parents) > 1:
        multi_parent_found = True
        print(f'MULTI-PARENT: {tid}')
        for src, rel in parents:
            print(f'  <- {src} ({rel})')
if not multi_parent_found:
    print('  none')

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
