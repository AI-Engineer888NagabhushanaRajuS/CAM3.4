"""AST evaluator with Excel array semantics.

Two evaluation modes:
- scalar context: ranges collapse to a single value (implicit intersection on
  the current row when shapes allow, else top-left) - how most formulas work.
- array context: ranges stay ranges and arithmetic/comparison operators act
  elementwise. Entered when a function requests an array argument
  (SUMPRODUCT, MATCH over computed arrays) or when an operator directly
  combines two ranges (then the result is an array the enclosing INDEX/MATCH/
  SUM consumes). This covers the corpus patterns:
    MATCH(1, INDEX((A=fg)*(C=cpn)*(UPPER(TRIM(AF))="TRUE"),0),0)
    SUMPRODUCT(--(range=crit), --(range2), values)
"""
from __future__ import annotations

from .parser import (Node, Num, Str, Bool, Err, CellRef, RangeRef, FuncCall,
                     BinOp, UnOp, Percent, NameRef, DynRange, TableRef, Empty)
from .values import (ErrorValue, Range, BLANK, NA, VALUE_ERR, REF_ERR, DIV0,
                     NAME_ERR, NUM_ERR, is_error, is_blank, to_number, to_text,
                     to_bool, compare)
from .functions import FUNCTIONS, _RawArg


class CircularRef(Exception):
    pass


class EvalContext:
    """Bridge between evaluator and the workbook model."""

    def __init__(self, workbook, current_sheet, current_row, current_col,
                 today_serial, stack=None):
        self.workbook = workbook
        self.current_sheet = current_sheet
        self.current_row = current_row
        self.current_col = current_col
        self.today_serial = today_serial
        self.stack = stack if stack is not None else set()
        self.unsupported = []  # collects notes: unsupported names etc.

    # -- value access --

    def cell_value(self, sheet, row, col):
        return self.workbook.get_value(sheet or self.current_sheet, row, col, self)

    def range_values(self, ref: RangeRef) -> Range:
        return self.workbook.get_range(ref, self)

    def formula_text_of(self, ref_node):
        if isinstance(ref_node, (CellRef,)):
            return self.workbook.get_formula(ref_node.sheet or self.current_sheet, ref_node.row, ref_node.col)
        return VALUE_ERR

    def defined_name(self, name):
        return self.workbook.get_defined_name(name, self)

    def resolve_table(self, node: TableRef, return_reference=False):
        """Resolve a structured ref to a Range (reuses range dep tracking).
        Row selectors: thisrow / totals / headers / data / all.
        Unknown table -> NAME_ERR + note; unknown column -> REF_ERR + note."""
        tname = node.table
        if tname is None:
            self.unsupported.append("bare-structured-ref")
            return Range(((NAME_ERR,),))
        tbl = self.workbook.get_table(tname)
        if tbl is None:
            self.unsupported.append(f"table:{tname}")
            return Range(((NAME_ERR,),))
        sheet, r1, c1, r2, c2, hdr_rows, tot_rows = tbl
        data_r1 = r1 + (hdr_rows if hdr_rows else 0)
        data_r2 = r2 - (tot_rows if tot_rows else 0)
        row_sel, col_name = node.selectors()
        # column index from the header row
        col = None
        if col_name is not None:
            want = " ".join(col_name.split()).lower()
            for c in range(c1, c2 + 1):
                hv = self.cell_value(sheet, r1, c)
                if isinstance(hv, str) and " ".join(hv.split()).lower() == want:
                    col = c
                    break
            if col is None:
                self.unsupported.append(f"table-col:{tname}[{col_name}]")
                return Range(((REF_ERR,),))
        sel = row_sel or "data"
        if sel == "thisrow":
            if not (data_r1 <= self.current_row <= data_r2):
                return Range(((VALUE_ERR,),))
            tr1 = tr2 = self.current_row
        elif sel == "totals":
            if not tot_rows:
                return Range(((REF_ERR,),))
            tr1 = tr2 = r2
        elif sel == "headers":
            tr1 = tr2 = r1
        elif sel == "data":
            tr1, tr2 = data_r1, max(data_r1, data_r2)
        elif sel == "all":
            tr1, tr2 = r1, r2
        else:
            self.unsupported.append(f"table-sel:{row_sel}")
            return Range(((NAME_ERR,),))
        ref = RangeRef(sheet, None, tr1, col if col is not None else c1,
                       tr2, col if col is not None else c2)
        return ref if return_reference else self.range_values(ref)

    # -- arg adapters used by functions.py --

    def scalar(self, arg, catch_errors=True):
        """Evaluate an argument node (or _RawArg) to a scalar value."""
        if isinstance(arg, _RawArg):
            v = arg.v
        else:
            v = evaluate(arg, self, array=False)
        if isinstance(v, Range):
            v = self._implicit_intersect(v)
        return v

    def resolve_arg(self, arg, array=False):
        """Evaluate keeping Range shape (for lookup/aggregation functions)."""
        if isinstance(arg, _RawArg):
            return arg.v
        return evaluate(arg, self, array=array)

    def reference_shape(self,arg):
        """Logical rectangle without materializing unused blank cells."""
        ref=self.resolve_table(arg,return_reference=True) if isinstance(arg,TableRef) else arg
        if isinstance(ref,CellRef):return (1,1)
        if isinstance(ref,DynRange):
            resolved = _dynamic_reference(ref, self)
            if not is_error(resolved):
                ref = resolved
        if not isinstance(ref,RangeRef):return None
        nr=1048576 if ref.whole_cols else ref.r2-ref.r1+1
        nc=16384 if ref.whole_rows else ref.c2-ref.c1+1
        return nr,nc

    def reference_cell_count(self,arg):
        shape=self.reference_shape(arg)
        return shape[0]*shape[1] if shape else None

    def subtotal_values(self, arg, code):
        """Reference-aware subset: manual hidden rows for101+, nested calls.
        Return None for unsupported provenance or active filtered-row semantics.
        """
        ref = self.resolve_table(arg, return_reference=True) if isinstance(arg, TableRef) else arg
        if isinstance(ref, CellRef):
            ref = RangeRef(ref.sheet,ref.ext,ref.row,ref.col,ref.row,ref.col)
        if not isinstance(ref, RangeRef) or ref.ext is not None:
            self.unsupported.append("subtotal-reference-provenance")
            return None
        sheet = ref.sheet or self.current_sheet
        sd = self.workbook._sheet(sheet)
        if sd is None:
            return [REF_ERR]
        r1,r2 = (1,sd.max_row) if ref.whole_cols else (ref.r1,ref.r2)
        c1,c2 = (1,sd.max_col) if ref.whole_rows else (ref.c1,ref.c2)
        active = getattr(sd, 'active_filter_ranges', None)
        if active is None and sd.filter_present:
            self.unsupported.append("subtotal-filter-metadata-unverified")
            return None
        # The filter's top row is a header, never filtered; data is top+1..bottom.
        # Deliberately row-wide/conservative: hidden state does not prove cause.
        intersects=[bounds for bounds in (active or []) if r1 <= bounds[3] and r2 > bounds[1]]
        region=getattr(sd,'text_filter_region',None)
        if intersects and (not getattr(sd,'text_filter_applied',False) or code>=101 or len(active)!=1 or region is None or tuple(active[0])!=tuple(region['bounds'])):
            self.unsupported.append("subtotal-active-filter-unsupported")
            return None
        values=[]
        from .parser import lex, T_FUNC
        for r in range(r1,r2+1):
            if intersects and region['bounds'][1] < r <= region['bounds'][3]:
                # Read every selected criterion column, even for a currently
                # excluded row, so edits establish/invalidate all relevant edges.
                from .text_filters import ascii_literal,custom_text_match
                keep=True
                for column,allowed in region['columns']:
                    criterion=self.cell_value(sheet,r,column)
                    if is_blank(criterion) or criterion=='':
                        if isinstance(allowed,dict)and allowed.get('kind')=='custom':
                            self.unsupported.append('subtotal-custom-text-filter-blank-unsupported')
                            return None
                        keep=keep and(isinstance(allowed,dict)and allowed.get('blank',False));continue
                    if not ascii_literal(criterion):
                        self.unsupported.append("subtotal-text-filter-value-unsupported")
                        return None
                    matched=custom_text_match(criterion,allowed)if isinstance(allowed,dict)and allowed.get('kind')=='custom'else criterion.lower() in(allowed['values']if isinstance(allowed,dict)else allowed)
                    keep=keep and matched
                if not keep:continue
            if code >= 101 and r in sd.hidden_rows:
                continue
            for c in range(c1,c2+1):
                f = sd.formulas.get((r,c))
                if f and any(t.kind==T_FUNC and t.value.removeprefix("_XLFN.")=="SUBTOTAL" for t in lex(f)):
                    continue
                values.append(self.cell_value(sheet,r,c))
        return values

    def index_reference(self, arg, rn, cn, nargs):
        """Select reference cell without evaluating every cell in INDEX input."""
        ref = self.resolve_table(arg, return_reference=True) if isinstance(arg, TableRef) else arg
        if isinstance(ref, DynRange):
            resolved = _dynamic_reference(ref, self)
            if is_error(resolved):return True, resolved
            ref = resolved
        if not isinstance(ref, RangeRef):
            return False, None
        r1, r2 = (1, 1048576) if ref.whole_cols else (ref.r1, ref.r2)
        c1, c2 = (1, 16384) if ref.whole_rows else (ref.c1, ref.c2)
        nr, nc = r2-r1+1, c2-c1+1
        ri, ci = int(rn), int(cn)
        if nr == 1 and nc > 1 and nargs == 2:
            ri, ci = 1, int(rn)
        if ri == 0 or ci == 0:
            return False, None
        if not (1 <= ri <= nr and 1 <= ci <= nc):
            return True, REF_ERR
        sheet = ref.sheet or self.current_sheet
        v = self.workbook.get_external_cell(ref.ext,sheet,r1+ri-1,c1+ci-1) if ref.ext is not None else self.cell_value(sheet,r1+ri-1,c1+ci-1)
        return True, v if arg is getattr(self,"_concat_index_arg",None) else (0.0 if is_blank(v) else v)

    def aggregation_extent(self,sum_arg,criteria_args,pairs):
        """Extend criteria scans to occupied union without eager sum-cell reads."""
        refs=[]
        for arg in [sum_arg]+list(criteria_args):
            ref=self.resolve_table(arg,return_reference=True) if isinstance(arg,TableRef) else arg
            if isinstance(ref,DynRange):
                resolved = _dynamic_reference(ref, self)
                if is_error(resolved):return resolved
                ref = resolved
            refs.append(ref)
        shapes=[self.reference_shape(a) for a in [sum_arg]+list(criteria_args)]
        if not all(s is not None for s in shapes):return pairs
        if any(s!=shapes[0] for s in shapes):return VALUE_ERR
        if not all(isinstance(r,RangeRef) and r.ext is None for r in refs):return pairs
        nr=nc=0
        for ref in refs:
            sd=self.workbook._sheet(ref.sheet or self.current_sheet)
            if sd is None:return REF_ERR
            r1=1 if ref.whole_cols else ref.r1;c1=1 if ref.whole_rows else ref.c1
            nr=max(nr,max(1,min(shapes[0][0],sd.max_row-r1+1)))
            nc=max(nc,max(1,min(shapes[0][1],sd.max_col-c1+1)))
        # Track original sum geometry for future input growth, without fetching
        # excluded cells (which could manufacture a circular dependency).
        self.workbook.record_reference(refs[0],self)
        if nr*nc>2000000:
            self.unsupported.append("aggregation:occupied-scan-budget")
            return NAME_ERR
        out=[]
        for (r,crit) in pairs:
            rr=r if isinstance(r,Range) else Range(((r,),))
            if rr.nrows==nr and rr.ncols==nc:out.append((rr,crit));continue
            out.append((Range(tuple(tuple(rr.cells[i][j] if i<rr.nrows and j<rr.ncols else BLANK
                                         for j in range(nc)) for i in range(nr))),crit))
        return out

    def selected_values(self, arg, hits):
        """Resolve only matched sum/average cells, not excluded dependencies.
        Validated by a separate LibreOffice SUMIFS self-exclusion fixture.
        Criteria ranges still record all their dependencies.
        """
        ref = arg
        if isinstance(ref, DynRange):
            resolved = _dynamic_reference(ref, self)
            if is_error(resolved):return [resolved]
            ref = resolved
        if isinstance(ref, RangeRef):
            sheet = ref.sheet or self.current_sheet
            r1 = 1 if ref.whole_cols else ref.r1
            c1 = 1 if ref.whole_rows else ref.c1
            values = []
            for ri, ci in hits:
                if ref.ext is not None:
                    v = self.workbook.get_external_cell(ref.ext, sheet, r1 + ri, c1 + ci)
                else:
                    v = self.cell_value(sheet, r1 + ri, c1 + ci)
                values.append(v)
            return values
        resolved = self.resolve_arg(arg)
        if is_error(resolved):
            return [resolved]
        if not isinstance(resolved, Range):
            resolved = Range(((resolved,),))
        return [resolved.cells[ri][ci] if ri < resolved.nrows and ci < resolved.ncols else BLANK for ri, ci in hits]

    def _implicit_intersect(self, rng: Range):
        if rng.nrows == 1 and rng.ncols == 1:
            return rng.cells[0][0]
        # same-row / same-column intersection against the current cell
        if rng.row0 is not None and rng.nrows == 1:
            return rng.cells[0][0] if rng.ncols == 1 else rng.cells[0][min(self.current_col - (rng.col0 or 1), rng.ncols - 1) if 0 <= self.current_col - (rng.col0 or 1) < rng.ncols else 0]
        if rng.col0 is not None and rng.ncols == 1:
            off = self.current_row - (rng.row0 or 1)
            if 0 <= off < rng.nrows:
                return rng.cells[off][0]
            return VALUE_ERR
        return rng.cells[0][0]


# ---------------- evaluation ----------------

def evaluate(node: Node, ctx: EvalContext, array=False):
    if isinstance(node, Num):
        return node.v
    if isinstance(node, Str):
        return node.v
    if isinstance(node, Bool):
        return node.v
    if isinstance(node, Err):
        return node.v
    if isinstance(node, CellRef):
        if node.ext is not None:
            return ctx.workbook.get_external_cell(node.ext, node.sheet, node.row, node.col)
        # Workbook scheduler diagnoses cycles and long acyclic chains.
        return ctx.cell_value(node.sheet, node.row, node.col)
    if isinstance(node, RangeRef):
        return ctx.range_values(node)
    if isinstance(node, NameRef):
        v = ctx.defined_name(node.name)
        if v is None:
            ctx.unsupported.append(f"defined-name:{node.name}")
            return NAME_ERR
        return v
    if isinstance(node, DynRange):
        return _eval_dynrange(node, ctx)
    if isinstance(node, TableRef):
        return ctx.resolve_table(node)
    if isinstance(node, Empty):
        return 0.0
    if isinstance(node, Percent):
        v = evaluate(node.x, ctx, array=array)
        return _elementwise1(v, lambda x: _arith_const(x, 0.01))
    if isinstance(node, UnOp):
        v = evaluate(node.x, ctx, array=array)
        if node.op == "-":
            return _elementwise1(v, _negate)
        return v
    if isinstance(node, BinOp):
        return _eval_binop(node, ctx, array)
    if isinstance(node, FuncCall):
        return _eval_func(node, ctx, array)
    raise TypeError(f"unknown node {type(node)}")


def _index_endpoint(node, ctx):
    """A validated scalar reference endpoint, never a whole-row/column point."""
    import math
    if isinstance(node, CellRef):
        if not (1 <= node.row <= 1048576 and 1 <= node.col <= 16384):return REF_ERR
        return (node.sheet or ctx.current_sheet, node.ext, node.row, node.col)
    if not isinstance(node, FuncCall) or node.name.removeprefix('_XLFN.') != 'INDEX' or len(node.args) not in (2, 3):
        return None
    ref = node.args[0]
    if not isinstance(ref, RangeRef) or ref.ext is not None:return None
    if len(node.args) == 3:
        # Bounded rectangular point selections only. Zero selectors are
        # row/column references and need a separate geometry implementation.
        if ref.whole_cols or ref.whole_rows:
            ctx.unsupported.append('dynrange:three-arg-unbounded-index-endpoint')
            return NAME_ERR
        if not (1 <= ref.r1 <= ref.r2 <= 1048576 and 1 <= ref.c1 <= ref.c2 <= 16384):return REF_ERR
        selectors = []
        for arg in node.args[1:]:
            value = to_number(ctx.scalar(arg))
            if is_error(value):return value
            if not math.isfinite(value):return NUM_ERR
            selectors.append(math.trunc(value))
        row, col = selectors
        if row == 0 or col == 0:
            ctx.unsupported.append('dynrange:zero-index-endpoint-geometry')
            return NAME_ERR
        if not (1 <= row <= ref.r2-ref.r1+1 and 1 <= col <= ref.c2-ref.c1+1):return REF_ERR
        return (ref.sheet or ctx.current_sheet, ref.ext, ref.r1+row-1, ref.c1+col-1)
    off = to_number(ctx.scalar(node.args[1]))
    if is_error(off):return off
    if not math.isfinite(off):return NUM_ERR
    n = math.trunc(off)
    if n == 0:
        ctx.unsupported.append('dynrange:zero-index-endpoint-geometry')
        return NAME_ERR
    if n < 0:return REF_ERR
    if ref.whole_cols and ref.c1 == ref.c2:
        return (ref.sheet or ctx.current_sheet, ref.ext, n, ref.c1) if n <= 1048576 else REF_ERR
    if ref.whole_rows and ref.r1 == ref.r2:
        return (ref.sheet or ctx.current_sheet, ref.ext, ref.r1, n) if n <= 16384 else REF_ERR
    if not ref.whole_cols and not ref.whole_rows and ref.c1 == ref.c2:
        return (ref.sheet or ctx.current_sheet, ref.ext, ref.r1+n-1, ref.c1) if n <= ref.r2-ref.r1+1 else REF_ERR
    if not ref.whole_cols and not ref.whole_rows and ref.r1 == ref.r2:
        return (ref.sheet or ctx.current_sheet, ref.ext, ref.r1, ref.c1+n-1) if n <= ref.c2-ref.c1+1 else REF_ERR
    ctx.unsupported.append('dynrange:non-vector-index-endpoint')
    return NAME_ERR


def _dynamic_reference(node, ctx):
    """One binding path shared by materialized and selected-reference reads."""
    a = _index_endpoint(node.l, ctx)
    if is_error(a):return a
    b = _index_endpoint(node.r, ctx)
    if is_error(b):return b
    if a is None or b is None:
        ctx.unsupported.append('dynrange-shape')
        return REF_ERR
    if a[0].lower() != b[0].lower() or a[1] != b[1]:
        ctx.unsupported.append('dynrange:mixed-sheet-or-book-endpoints')
        return NAME_ERR
    if a[2] > b[2] or a[3] > b[3]:
        ctx.unsupported.append('dynrange:reversed-endpoint-geometry')
        return NAME_ERR
    return RangeRef(a[0], a[1], a[2], a[3], b[2], b[3])


def _eval_dynrange(node: DynRange, ctx: EvalContext):
    ref = _dynamic_reference(node, ctx)
    return ref if is_error(ref) else ctx.range_values(ref)


def _eval_func(node: FuncCall, ctx: EvalContext, array=False):
    name = node.name.removeprefix("_XLFN.")
    fn = FUNCTIONS.get(name)
    if fn is None:
        ctx.unsupported.append(f"function:{node.name}")
        return NAME_ERR
    # Preserve explicit empty arguments. They are distinct from absent args:
    # VLOOKUP(...,2,) coerces empty to FALSE; VLOOKUP(...,2) defaults TRUE.
    args = list(node.args)
    # Pre-evaluate cell/range args to nodes; functions receive raw AST nodes
    # and pull values via ctx (so IF short-circuits and IFERROR can catch).
    previous=getattr(ctx,'_function_array_context',False)
    ctx._function_array_context=array
    try:return fn(args,ctx)
    finally:ctx._function_array_context=previous


def _concat_operand(node, ctx, array):
    # Narrow reference INDEX operand only. Preserve the selected blank until
    # text coercion, while standalone INDEX and computed arrays retain behavior.
    previous=getattr(ctx,"_concat_index_arg",None)
    selected=node
    # Only a direct IFERROR primary INDEX inherits this text-coercion scope.
    # Fallback expressions, other wrappers and computed arrays do not inherit it.
    if isinstance(node,FuncCall) and node.name.removeprefix("_XLFN.")=="IFERROR" and len(node.args)==2:
        selected=node.args[0]
    if isinstance(selected,FuncCall) and selected.name.removeprefix("_XLFN.")=="INDEX" and selected.args:
        ctx._concat_index_arg=selected.args[0]
    try:return evaluate(node,ctx,array=array)
    finally:ctx._concat_index_arg=previous


def _eval_binop(node: BinOp, ctx: EvalContext, array: bool):
    op = node.op
    if op in ("=", "<>", "<", "<=", ">", ">="):
        l = evaluate(node.l, ctx, array=True)
        r = evaluate(node.r, ctx, array=True)
        if isinstance(l, Range) or isinstance(r, Range):
            return _elementwise2(l, r, lambda a, b: _cmp_op(op, a, b))
        c = compare(l, r)
        if is_error(c):
            return c
        return {"=": c == 0, "<>": c != 0, "<": c < 0, "<=": c <= 0, ">": c > 0, ">=": c >= 0}[op]
    if op == "&":
        l = _concat_operand(node.l, ctx, array)
        r = _concat_operand(node.r, ctx, array)
        if isinstance(l, Range) or isinstance(r, Range):
            return _elementwise2(l, r, _concat)
        a = to_text(l)
        if is_error(a):
            return a
        b = to_text(r)
        if is_error(b):
            return b
        return a + b
    # arithmetic
    l = evaluate(node.l, ctx, array=True)
    r = evaluate(node.r, ctx, array=True)
    if isinstance(l, Range) or isinstance(r, Range):
        return _elementwise2(l, r, lambda a, b: _arith(op, a, b))
    return _arith(op, l, r)


def _cmp_op(op, a, b):
    c = compare(a, b)
    if is_error(c):
        return c
    return {"=": c == 0, "<>": c != 0, "<": c < 0, "<=": c <= 0, ">": c > 0, ">=": c >= 0}[op]


def _concat(a, b):
    ta = to_text(a)
    if is_error(ta):
        return ta
    tb = to_text(b)
    if is_error(tb):
        return tb
    return ta + tb


def _arith(op, a, b):
    if is_error(a):
        return a
    if is_error(b):
        return b
    x = to_number(a)
    if is_error(x):
        return x
    y = to_number(b)
    if is_error(y):
        return y
    if op == "+":
        return x + y
    if op == "-":
        return x - y
    if op == "*":
        return x * y
    if op == "/":
        if y == 0:
            return DIV0
        return x / y
    if op == "^":
        try:
            if x == 0 and y < 0:
                return DIV0
            return x ** y
        except (OverflowError, ZeroDivisionError):
            return NUM_ERR
    return VALUE_ERR


def _arith_const(a, k):
    if is_error(a):
        return a
    x = to_number(a)
    if is_error(x):
        return x
    return x * k


def _negate(a):
    # Excel --(bool): 1/0 ; --(text-number): number ; --(other text): #VALUE!
    if is_error(a):
        return a
    n = to_number(a)
    if is_error(n):
        return n
    return -n


def _elementwise1(v, f):
    if isinstance(v, Range):
        return Range(tuple(tuple(f(x) for x in row) for row in v.cells))
    return f(v)


def _elementwise2(l, r, f):
    if isinstance(l, Range) and isinstance(r, Range):
        nrows = max(l.nrows, r.nrows)
        ncols = max(l.ncols, r.ncols)
        out = []
        for ri in range(nrows):
            row = []
            for ci in range(ncols):
                a = l.cells[ri % l.nrows][ci % l.ncols] if (l.nrows in (1, nrows) and l.ncols in (1, ncols)) else NA
                b = r.cells[ri % r.nrows][ci % r.ncols] if (r.nrows in (1, nrows) and r.ncols in (1, ncols)) else NA
                if l.nrows * l.ncols == 1:
                    a = l.cells[0][0]
                if r.nrows * r.ncols == 1:
                    b = r.cells[0][0]
                row.append(f(a, b))
            out.append(tuple(row))
        return Range(tuple(out))
    if isinstance(l, Range):
        return Range(tuple(tuple(f(x, r) for x in row) for row in l.cells))
    if isinstance(r, Range):
        return Range(tuple(tuple(f(l, x) for x in row) for row in r.cells))
    return f(l, r)
