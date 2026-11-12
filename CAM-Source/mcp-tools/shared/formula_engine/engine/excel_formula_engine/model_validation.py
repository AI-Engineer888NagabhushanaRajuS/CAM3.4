"""Read-only model identity diagnostics. No deduplication or quantity repair.

The caller supplies comparison-key and occurrence-identity fields from an
explicit source contract. A collision is evidence to review, not authority to
sum, drop, choose an MPN or change a bill of materials.
"""
from collections import defaultdict


def identity_collisions(records,comparison_fields,occurrence_fields,quantity_field):
    comparison_fields=tuple(comparison_fields);occurrence_fields=tuple(occurrence_fields)
    if not comparison_fields or not occurrence_fields:
        raise ValueError('Explicit comparison and occurrence identity fields required')
    groups=defaultdict(list);missing=[]
    required=set(comparison_fields+occurrence_fields+(quantity_field,))
    for i,row in enumerate(records):
        absent=sorted(k for k in required if k not in row or row[k] is None)
        if absent:missing.append({'row_index':i,'missing_fields':absent})
        groups[tuple(row.get(k) for k in comparison_fields)].append((i,row))
    collisions=[]
    for key,items in groups.items():
        if len(items)<2:continue
        identities={tuple(row.get(k) for k in occurrence_fields) for _,row in items}
        quantities={repr(row.get(quantity_field)) for _,row in items}
        collisions.append({'comparison_key':list(key),'row_indexes':[i for i,_ in items],
                           'occurrence_identity_count':len(identities),'distinct_quantity_count':len(quantities),
                           'risk':'distinct-occurrences-share-dedup-key' if len(identities)>1 else
                                  'same-identity-conflicting-quantity' if len(quantities)>1 else
                                  'repeated-same-identity-values',
                           'action':'review source identity policy; no repair inferred'})
    return {'comparison_fields':list(comparison_fields),'occurrence_fields':list(occurrence_fields),
            'quantity_field':quantity_field,'collisions':collisions,'missing_identity':missing,
            'mutation':'none','policy':'No row dropped, summed, priced or selected'}
