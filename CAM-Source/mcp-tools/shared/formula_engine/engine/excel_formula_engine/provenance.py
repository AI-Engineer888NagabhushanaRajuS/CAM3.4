"""Read-only cell provenance and arithmetic diagnostics.

A literal is not automatically a user input: it can be a generator-derived
snapshot. Mapping it to a code payload requires explicit source evidence.
Diagnostics never rewrite cells or supply an approved financial answer.
"""
from dataclasses import dataclass,asdict
from decimal import Decimal,InvalidOperation

@dataclass(frozen=True)
class CellOrigin:
    sheet: str
    row: int
    col: int
    storage: str
    formula: str | None
    has_saved_value: bool
    origin_role: str
    source_binding: str | None = None

def describe_cell(workbook,sheet,row,col,origin_role=None,source_binding=None):
    sd=workbook._sheet(sheet)
    if sd is None:raise KeyError(sheet)
    formula=sd.formulas.get((row,col))
    storage='formula' if formula is not None else ('literal' if (row,col) in sd.cached else 'empty')
    if workbook.array_output_region(sheet,row,col) is not None and formula is None:
        storage='array-output-snapshot'
    if origin_role is None:
        origin_role='array-derived-uncomputed' if storage=='array-output-snapshot' else 'formula-derived' if storage=='formula' else 'unclassified-literal' if storage=='literal' else 'empty'
    return CellOrigin(sd.title,row,col,storage,formula,(row,col) in sd.cached,origin_role,source_binding)

def arithmetic_product_diagnostic(unit,quantity,extended,relative_tolerance=Decimal('1e-12')):
    """Numerical relationship only, not a financial rule or replacement value.
    Tolerance is a diagnostic precision threshold, not client approval.
    """
    if any(isinstance(x,bool) or not isinstance(x,(int,float,Decimal)) for x in (unit,quantity,extended)):
        return {'status':'not-numeric','mutation':'none'}
    try:u,q,e=(Decimal(str(x)) for x in (unit,quantity,extended))
    except InvalidOperation:return {'status':'not-numeric','mutation':'none'}
    if not all(x.is_finite() for x in (u,q,e)):return {'status':'non-finite','mutation':'none'}
    product=u*q;delta=e-product
    equal=abs(delta)<=relative_tolerance*max(abs(product),abs(e),Decimal(1))
    return {'status':'consistent' if equal else 'inconsistent','unit_times_quantity':str(product),
            'stored_extended':str(e),'difference':str(delta),'relative_tolerance':str(relative_tolerance),
            'authority':'diagnostic only; no approved correction implied','mutation':'none'}

@dataclass(frozen=True)
class OriginNode:
    key: str
    kind: str  # input, formula, generator-snapshot
    source_binding: str
    rebuild_recipe: str | None = None  # identifier only, never executed here
    policy_approved: bool = False

class OriginGraph:
    """Explicitly supplied model lineage, separate from runtime formula edges.

    This does not infer missing edges from XLSX cells and does not mutate a
    workbook. Formula candidates are not safe to publish while upstream model
    snapshots remain stale. Coverage is always scoped to declared nodes/edges.
    """
    def __init__(self):
        self.nodes={}
        self.consumers={}
    def add_node(self,node):
        if node.kind not in ('input','formula','generator-snapshot'):
            raise ValueError('Unknown origin kind')
        if not node.source_binding:raise ValueError('Evidence binding required')
        if node.key in self.nodes:raise ValueError('Duplicate origin key')
        self.nodes[node.key]=node
    def add_dependency(self,source,consumer):
        if source not in self.nodes or consumer not in self.nodes:raise KeyError('Declare both nodes first')
        # Reject cycles without inventing a fixed-point financial policy.
        seen=set();stack=[consumer]
        while stack:
            k=stack.pop()
            if k==source:raise ValueError('Model-lineage cycle requires explicit policy')
            if k in seen:continue
            seen.add(k);stack.extend(self.consumers.get(k,()))
        self.consumers.setdefault(source,set()).add(consumer)
    def impact(self,changed_keys):
        changed=set(changed_keys)
        if not changed<=self.nodes.keys():raise KeyError('Unknown changed origin')
        seen=set(changed);stack=list(changed)
        while stack:
            for c in self.consumers.get(stack.pop(),()):
                if c not in seen:seen.add(c);stack.append(c)
        affected=seen-changed
        snapshots=sorted(k for k in affected if self.nodes[k].kind=='generator-snapshot')
        blocked=sorted(k for k in snapshots if not self.nodes[k].rebuild_recipe or not self.nodes[k].policy_approved)
        return {'changed':sorted(changed),'affected':sorted(affected),
                'formula_recalc_candidates':sorted(k for k in affected if self.nodes[k].kind=='formula'),
                'model_rebuild_required':snapshots,'blocked_model_nodes':blocked,
                'declared_model_path_ready':not snapshots,
                'coverage':'declared lineage only; unknown edges are not certified',
                'mutation':'none'}
