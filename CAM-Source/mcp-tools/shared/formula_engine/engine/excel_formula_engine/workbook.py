"""Workbook model: openpyxl-backed sheet data, dependency graph, recalculation.

Key design decisions (traced to FE-3 design doc):
- Two openpyxl loads: formulas (data_only=False) and cached values
  (data_only=True). Tool-generated CAM workbooks carry NO cached values
  (openpyxl-written); human-built Internal workbooks do. The parity harness
  uses cached values where present and marks everything else unverifiable.
- Occupied reads can clamp range materialization; original legal geometry is
  retained for invalidation. Logical blank tails need function-specific handling,
  not an assumption that Excel ignores unused referenced cells.
- External workbook refs ([1]Sheet!A1) use source-identified external-link
  snapshots when available, otherwise #REF!. No target-formula cache fallback.
- Edits (set_value) invalidate dependents through the recorded dependency
  graph; evaluation is lazy with per-cell memo + cycle detection (#CIRC!).
"""
from __future__ import annotations

import datetime
import re
import time

from .parser import parse_formula, CellRef, RangeRef, ParseError, col_to_num
from .values import (ErrorValue, Range, BLANK, NA, VALUE_ERR, REF_ERR, NAME_ERR,
                     is_error, is_blank)
from .evaluator import EvalContext, evaluate


def _py_to_excel(v,cell_type=None,epoch=None):
    if cell_type=='e':
        return ErrorValue(str(v))  # Preserve source-typed provider/future error codes.
    if v is None:
        return BLANK
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        if cell_type is None and v.startswith("#") and v in ("#N/A", "#VALUE!", "#REF!", "#DIV/0!", "#NAME?", "#NUM!", "#NULL!"):
            return ErrorValue(v)
        return v
    if isinstance(v, (datetime.date, datetime.time, datetime.timedelta)):
        from openpyxl.utils.datetime import to_excel, WINDOWS_EPOCH
        return to_excel(v, epoch=WINDOWS_EPOCH if epoch is None else epoch)
    return str(v)


def _decode_external_cache_cell(value,cell_type):
 import math
 kind=cell_type or 'n'
 if kind not in ('n','str','b','e'):return REF_ERR,'unsupported-type:'+str(kind)
 if value is None:return BLANK,None
 if kind=='str':return str(value),None
 if kind=='e':
  from .parser import ERRORS
  if str(value) in ERRORS:return ErrorValue(str(value)),None
  return REF_ERR,'malformed-or-unsupported-error'
 if kind=='b':
  if value in ('0',0,False):return False,None
  if value in ('1',1,True):return True,None
  return REF_ERR,'malformed-boolean'
 try:
  number=float(value)
  if math.isfinite(number):return number,None
 except (ValueError,TypeError,OverflowError):pass
 return REF_ERR,'malformed-number'


class CalculationBudgetExceeded(Exception):
    """A computation was suspended; partial cached work is retained for retry."""
    pass


class _NeedCell(Exception):
    def __init__(self, key):
        self.key = key


class ExternalRef:
    __slots__ = ("book", "sheet", "row", "col")


class SheetData:
    __slots__ = ("formulas", "cached", "max_row", "max_col", "title", "hidden_rows", "filter_present", "active_filter_ranges", "text_filter_region", "text_filter_applied", "array_regions")

    def __init__(self, title):
        self.title = title
        self.hidden_rows = set()
        self.filter_present = False
        self.active_filter_ranges = []
        self.text_filter_region = None
        self.text_filter_applied = False
        self.array_regions = []
        self.formulas = {}   # (row,col) -> formula string (no leading =)
        self.cached = {}     # (row,col) -> excel value (static or cached)
        self.max_row = 1
        self.max_col = 1


class Workbook:
    def __init__(self, path=None, today=None, *, decimal_separator=".", group_separator=","):
        # Explicit caller configuration, not locale discovery from an XLSX file.
        if not isinstance(decimal_separator,str) or len(decimal_separator)!=1:
            raise ValueError('decimal_separator must be one character')
        if not isinstance(group_separator,str) or len(group_separator)>1 or decimal_separator==group_separator:
            raise ValueError('group_separator must be empty or one distinct character')
        self.number_decimal_separator=decimal_separator
        self.number_group_separator=group_separator
        self.sheets = {}           # lower title -> SheetData
        self.sheet_order = []
        self.cache = {}            # (sheet_l, row, col) -> computed value
        self.parsed = {}           # formula string -> AST (shared across cells)
        self.deps = {}             # (sheet,row,col) -> set of referenced keys
        self.rdeps = {}            # referenced cell key -> set of dependent keys
        self.rdeps_ranges = {}     # sheet_l -> set of (r1,c1,r2,c2, dependent key)
        self.defined_names = {}
        self.tables = {}         # lower name -> (sheet_l, r1,c1,r2,c2, header_rows, totals_rows)
        self.external_links = []   # raw external link info if any
        self.pivot_snapshots = []  # metadata-bound saved pivot display, no refresh
        self.notes = []            # provenance/unsupported notes
        self._scheduler_active = False
        self._range_read_scope = None
        self.cycle_diagnostics = []
        self.stats = {"evaluation_attempts": 0, "max_dependency_depth": 0, "cells_evaluated": 0, "parse_errors": 0,
                      "external_ref_cells": 0, "name_errors": 0}
        if today is None:
            today = datetime.date.today()
        base = datetime.date(1899, 12, 30)
        self.today_serial = (today - base).days
        self.date_system_1904 = False
        if path:
            self.load(path)

    # ---------- loading ----------

    def load(self, path):
        import openpyxl
        # Read the bytes once and load from memory: openpyxl keeps the file archive open until garbage collection, which
        # locked the workbook on Windows (the caller could not delete or rewrite it after a check).
        import io
        if hasattr(path, 'read'):
            raw = path.read()
            if hasattr(path, 'seek'):
                path.seek(0)
        else:
            with open(path, 'rb') as fh:
                raw = fh.read()
        wbf = openpyxl.load_workbook(io.BytesIO(raw), data_only=False, read_only=False, keep_links=True)
        wbv = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=False, keep_links=True)
        self.date_system_1904 = (wbf.epoch.year == 1904)
        from .text_filters import source_text_filters
        try: text_filter_regions=source_text_filters(path)
        except Exception: text_filter_regions={}  # active-filter evaluation fails closed below

        # Bind original numeric serials before openpyxl temporal roundtrips can
        # collapse 59/60 or lose sub-millisecond precision. Retained only at load.
        from .temporal_serials import source_temporal_values
        try:
            temporal_values = source_temporal_values(path, wbv)
        except Exception as exc:
            temporal_values = {}
            self.notes.append('temporal-source-load:' + type(exc).__name__)

        def convert_cell(cell, value):
            if isinstance(value, (datetime.date, datetime.time, datetime.timedelta)):
                source = temporal_values.get(cell.parent.title, {}).get(cell.coordinate)
                if source is None:
                    self.notes.append(f'temporal-source-unbound:{cell.parent.title}!{cell.coordinate}')
                    return NAME_ERR
                kind, serial = source
                if kind == 'number':
                    return serial
                return _py_to_excel(value, cell.data_type, epoch=wbf.epoch)
            return _py_to_excel(value, cell.data_type)

        for name in wbf.sheetnames:
            sd = SheetData(name)
            wsf = wbf[name]
            wsv = wbv[name] if name in wbv.sheetnames else None
            sd.hidden_rows = {r for r, d in wsf.row_dimensions.items() if d.hidden}
            sd.filter_present = bool(wsf.auto_filter.ref or any(wsf.tables[n].autoFilter for n in wsf.tables))
            # Save criteria-bearing regions, not just dropdown presence. Reapplying
            # Excel filters is not yet supported. Never infer cause from hidden flags.
            from openpyxl.utils.cell import range_boundaries
            filters = [wsf.auto_filter] + [wsf.tables[n].autoFilter for n in wsf.tables]
            sd.active_filter_ranges = [range_boundaries(f.ref) for f in filters
                                       if f is not None and f.ref and f.filterColumn]
            sd.text_filter_region = text_filter_regions.get(name)
            sd.max_row = max(wsf.max_row or 1, 1)
            sd.max_col = max(wsf.max_column or 1, 1)
            for row in wsf.iter_rows():
                for c in row:
                    if c.value is None:
                        continue
                    v = c.value
                    # legacy CSE array formulas surface as ArrayFormula objects
                    if type(v).__name__ == "ArrayFormula":
                        ref = getattr(v, "ref", None)
                        if not isinstance(ref,str) or not re.fullmatch(r"\$?[A-Za-z]{1,3}\$?[1-9][0-9]*(?::\$?[A-Za-z]{1,3}\$?[1-9][0-9]*)?",ref):
                            raise ValueError('array-output-metadata-unsupported')
                        ac1,ar1,ac2,ar2=range_boundaries(ref)
                        if not (1<=ar1<=ar2<=1048576 and 1<=ac1<=ac2<=16384 and (c.row,c.column)==(ar1,ac1)):
                            raise ValueError('array-output-metadata-unsupported')
                        if any(ar1<=rr2 and ar2>=rr1 and ac1<=cc2 and ac2>=cc1 for rr1,cc1,rr2,cc2 in sd.array_regions):
                            raise ValueError('array-output-metadata-overlap')
                        sd.array_regions.append((ar1,ac1,ar2,ac2))
                        v = getattr(v, "text", None)
                        if not isinstance(v,str) or not v.startswith('=') or not v[1:].strip():
                            raise ValueError('array-formula-text-unavailable')
                        if isinstance(v, str) and v.startswith("="):
                            sd.formulas[(c.row, c.column)] = v[1:]
                            if wsv is not None:
                                cv = wsv.cell(row=c.row, column=c.column).value
                                if cv is not None and type(cv).__name__ != "ArrayFormula":
                                    sd.cached[(c.row, c.column)] = convert_cell(wsv.cell(row=c.row,column=c.column),cv)
                        continue
                    if isinstance(v, str) and v.startswith("="):
                        sd.formulas[(c.row, c.column)] = v[1:]
                        # cached value (usually None for openpyxl-written files)
                        if wsv is not None:
                            cv = wsv.cell(row=c.row, column=c.column).value
                            if cv is not None:
                                sd.cached[(c.row, c.column)] = convert_cell(wsv.cell(row=c.row,column=c.column),cv)
                    else:
                        sd.cached[(c.row, c.column)] = convert_cell(c,c.value)
            # static cells present only in the value view (e.g. cached-only)
            if wsv is not None:
                for row in wsv.iter_rows():
                    for c in row:
                        if c.value is not None and (c.row, c.column) not in sd.cached:
                            sd.cached[(c.row, c.column)] = convert_cell(c,c.value)
            self.sheets[name.lower()] = sd
            self.sheet_order.append(name.lower())
            # structured tables (ListObjects) for Table[Col] reference support
            try:
                for tname in wsf.tables:
                    tbl = wsf.tables[tname]
                    ref = tbl.ref
                    m = re.match(r"^([A-Za-z]+)(\d+)(?::([A-Za-z]+)(\d+))?$", ref)
                    if not m:
                        self.notes.append(f"table:{tname} bad ref {ref!r}")
                        continue
                    c1n, r1n = col_to_num(m.group(1)), int(m.group(2))
                    c2n = col_to_num(m.group(3)) if m.group(3) else c1n
                    r2n = int(m.group(4)) if m.group(4) else r1n
                    hdr = tbl.headerRowCount if tbl.headerRowCount is not None else 1
                    tot = tbl.totalsRowCount or 0
                    self.tables[tname.lower()] = (name.lower(), r1n, c1n, r2n, c2n, hdr, tot)
            except Exception as e:
                self.notes.append(f"tables-load:{name}:{e}")
        from .pivot import extract_pivot_snapshots
        for ws in wbf:
            self.pivot_snapshots.extend(extract_pivot_snapshots(ws))
        # defined names
        try:
            for name, dn in wbf.defined_names.items():
                self.defined_names[name.upper()] = dn.value
        except Exception:
            for dn in getattr(wbf, "defined_names", []):
                self.defined_names[dn.name.upper()] = dn.value
        # external workbook link caches: [n] in formulas -> external_books[n-1]
        self.external_books = []
        try:
            for link in getattr(wbf, "_external_links", []) or []:
                book = {}
                eb = getattr(link, "externalBook", None)
                if eb is not None:
                    sn = getattr(eb, "sheetNames", None)
                    names = list(getattr(sn, "sheetName", []) or []) if sn is not None else []
                    sds = getattr(eb, "sheetDataSet", None)
                    for i, sdset in enumerate(getattr(sds, "sheetData", []) or []):
                        sid = getattr(sdset, "sheetId", i)
                        sname = names[sid].lower() if isinstance(sid, int) and sid < len(names) else str(sid)
                        for erow in getattr(sdset, "row", []) or []:
                            for cell in getattr(erow, "cell", []) or []:
                                rref = getattr(cell, "r", None)
                                cv = getattr(cell, "v", None)
                                m = re.fullmatch(r'([A-Z]+)([1-9][0-9]*)', str(rref))
                                if not m or not 1 <= int(m.group(2)) <= 1048576 or not 1 <= col_to_num(m.group(1)) <= 16384:
                                    self.notes.append(f'external-cache:{len(self.external_books)+1}:invalid-cell-reference')
                                    continue
                                if int(m.group(2)) != erow.r:
                                    self.notes.append(f'external-cache:{len(self.external_books)+1}:{sname}!{rref}:parent-row-mismatch')
                                    continue
                                value, note = _decode_external_cache_cell(cv, getattr(cell, 't', None))
                                if note:
                                    self.notes.append(f'external-cache:{len(self.external_books)+1}:{sname}!{rref}:{note}')
                                book[(sname, int(m.group(2)), col_to_num(m.group(1)))] = value
                self.external_books.append(book)
            if self.external_books:
                self.notes.append(f"external-links: loaded {len(self.external_books)} cached book(s)")
        except Exception as e:
            self.notes.append(f"external-links-load:{e}")
        self._wb = wbf

    def get_external_cell(self, ext, sheet, row, col):
        """Cached value from an external workbook link ([n]Sheet!A1)."""
        try:
            book = self.external_books[int(ext) - 1]
        except (IndexError, ValueError):
            return REF_ERR
        return book.get(((sheet or "").lower(), row, col), REF_ERR)

    # ---------- accessors ----------

    def _sheet(self, name):
        sd = self.sheets.get(name.lower()) if name else None
        if sd is None:
            return None
        return sd

    def get_formula(self, sheet, row, col):
        sd = self._sheet(sheet)
        if sd is None:
            return REF_ERR
        f = sd.formulas.get((row, col))
        return f if f is not None else ""

    def get_table(self, name):
        return self.tables.get(name.lower())

    def add_table(self, name, sheet, ref, header_rows=1, totals_rows=0):
        """Register a table programmatically (tests / in-memory workbooks)."""
        m = re.match(r"^([A-Za-z]+)(\d+)(?::([A-Za-z]+)(\d+))?$", ref)
        c1n, r1n = col_to_num(m.group(1)), int(m.group(2))
        c2n = col_to_num(m.group(3)) if m.group(3) else c1n
        r2n = int(m.group(4)) if m.group(4) else r1n
        self.tables[name.lower()] = (sheet.lower(), r1n, c1n, r2n, c2n, header_rows, totals_rows)

    def get_defined_name(self, name, ctx):
        # Defined-name metadata exists in inspected source workbooks.
        # Arbitrary stored name references remain unsupported; no activation here.
        v = self.defined_names.get(name.upper())
        if v is None:
            return None
        self.notes.append(f"defined-name:{name} unresolved-storage")
        return None  # stored as ref text; arbitrary name-string resolution is not implemented

    def array_output_region(self, sheet, row, col):
        """Declared stored array geometry only; never inferred spill ownership."""
        sd=self._sheet(sheet)
        if sd is None:return None
        for r1,c1,r2,c2 in sd.array_regions:
            if r1<=row<=r2 and c1<=col<=c2:return (r1,c1,r2,c2)
        return None

    def _array_follower_refusal(self, sd, row, col):
        region=self.array_output_region(sd.title,row,col)
        if region is not None and (row,col)!=region[:2]:
            note=f"array-output-uncomputed:{sd.title}!R{row}C{col}; owner=R{region[0]}C{region[1]}; saved follower is not a calculated literal"
            if note not in self.notes:self.notes.append(note)
            return True
        return False

    def get_value(self, sheet, row, col, ctx: EvalContext):
        sd = self._sheet(sheet)
        if sd is None:
            return REF_ERR
        if self._array_follower_refusal(sd,row,col):return NAME_ERR
        key = (sd.title.lower(), row, col)
        if key in self.cache:
            return self.cache[key]
        f = sd.formulas.get((row, col))
        if f is None:
            return sd.cached.get((row, col), BLANK)
        if self._scheduler_active:
            raise _NeedCell(key)
        return self._eval_cell(sd, row, col, f, ctx)

    def _eval_cell(self, sd, row, col, formula, ctx):
        key = (sd.title.lower(), row, col)
        if key in self.cache:
            return self.cache[key]
        if key in ctx.stack:
            self.notes.append(f"circular:{key}")
            self.cache[key] = ErrorValue("#CIRC!")
            return self.cache[key]
        ast = self.parsed.get(formula)
        if ast is None:
            try:
                ast = parse_formula(formula)
            except ParseError as e:
                self.stats["parse_errors"] += 1
                self.parsed[formula] = ("ERR", str(e))
                if str(e).startswith("unsupported-reference:"):
                    self.notes.append(f"{key}:{e}")
                self.cache[key] = NAME_ERR
                return self.cache[key]
            self.parsed[formula] = ast
        if isinstance(ast, tuple) and ast[0] == "ERR":
            if ast[1].startswith("unsupported-reference:"):
                self.notes.append(f"{key}:{ast[1]}")
            self.cache[key] = NAME_ERR
            return self.cache[key]
        sub = EvalContext(self, sd.title, row, col, self.today_serial, ctx.stack | {key})
        self.stats["evaluation_attempts"] += 1
        # record dependencies
        deps = set()
        tracker = _DepTracker(self, deps)
        sub.workbook = tracker
        val = evaluate(ast, sub)
        if isinstance(val, Range):
            # top-level formula result that is a range: Excel collapses by
            # implicit intersection on the formula cell's row/col
            val = sub._implicit_intersect(val)
        if sub.unsupported:
            for u in sub.unsupported:
                self.notes.append(f"{key}:{u}")
                if u.startswith("function:") or u.startswith("defined-name:"):
                    self.stats["name_errors"] += 1
        self.cache[key] = val
        self.stats["cells_evaluated"] += 1
        self._replace_dependencies(key, deps)
        return val

    def _clear_dependencies(self, key):
        """Detach only this formula's outgoing edges, not its consumers.

        Interrupted evaluations retain conservative provisional cell edges in
        deps until a successful evaluation or explicit replacement clears them.
        """
        for dep in self.deps.pop(key, set()):
            if len(dep) == 3:
                consumers = self.rdeps.get(dep)
                if consumers is not None:
                    consumers.discard(key)
                    if not consumers:
                        self.rdeps.pop(dep, None)
            else:
                entries = self.rdeps_ranges.get(dep[0])
                if entries is not None:
                    entries.discard((dep[1], dep[2], dep[3], dep[4], key))
                    if not entries:
                        self.rdeps_ranges.pop(dep[0], None)

    def _replace_dependencies(self, key, deps):
        self._clear_dependencies(key)
        self.deps[key] = deps
        for dep in deps:
            if len(dep) == 3:
                self.rdeps.setdefault(dep, set()).add(key)
            else:
                self.rdeps_ranges.setdefault(dep[0], set()).add(
                    (dep[1], dep[2], dep[3], dep[4], key))

    def record_reference(self,ref,ctx):
        """Base adapter no-op; dependency tracker records without cell reads."""
        return None

    def get_range(self, ref: RangeRef, ctx: EvalContext) -> Range:
        if ref.ext is not None:
            return self._external_range(ref, ctx)
        sd = self._sheet(ref.sheet or ctx.current_sheet)
        if sd is None:
            return Range(((REF_ERR,),))
        r1, r2 = ref.r1, ref.r2
        c1, c2 = ref.c1, ref.c2
        if ref.whole_cols:
            r1, r2 = 1, sd.max_row
        if ref.whole_rows:
            c1, c2 = 1, sd.max_col
        r2 = min(r2, max(sd.max_row, r1))
        c2 = min(c2, max(sd.max_col, c1))
        rows = []
        for r in range(r1, r2 + 1):
            row = []
            for c in range(c1, c2 + 1):
                row.append(self.get_value(sd.title, r, c, ctx))
            rows.append(tuple(row))
        return Range(tuple(rows), sheet=sd.title, row0=r1, col0=c1)

    def _external_range(self, ref, ctx):
        self.stats["external_ref_cells"] += 1
        if ref.r1 is not None and ref.c1 is not None:
            rows = []
            for r in range(ref.r1, (ref.r2 or ref.r1) + 1):
                row = []
                for c in range(ref.c1, (ref.c2 or ref.c1) + 1):
                    row.append(self.get_external_cell(ref.ext, ref.sheet, r, c))
                rows.append(tuple(row))
            if rows:
                return Range(tuple(rows), sheet=ref.sheet, row0=ref.r1, col0=ref.c1)
        self.notes.append(f"external-ref-unresolved:[{ref.ext}]{ref.sheet}!")
        return Range(((REF_ERR,),))

    # ---------- edits / recalc ----------

    def reapply_text_filters(self, sheet):
        """Explicit local text-list reapply, not automatic Excel UI synchronization.

        Supports strict worksheet ASCII literal lists (optionally blank-selected)
        or custom equal/notEqual
        text criteria for SUBTOTAL1-11 (new statistical codes have typed/numeric
        domain guards); custom-filter blanks fail closed.
        No workbook/hidden-state writes. Any later model edit invalidates this
        permission/view conservatively, including cross-sheet formula inputs.
        """
        sd=self._sheet(sheet)
        if sd is None:raise KeyError(sheet)
        if sd.text_filter_region is None or len(sd.active_filter_ranges)!=1 or tuple(sd.active_filter_ranges[0])!=tuple(sd.text_filter_region['bounds']):
            raise ValueError('text-filter-reapply-unsupported')
        sd.text_filter_applied=True
        self.cache.clear()
        return {'sheet':sd.title,'bounds':sd.text_filter_region['bounds'],'scope':'ASCII literal lists with optional blanks/custom equal-notEqual; SUBTOTAL1-11 with statistical typed/numeric guards','writes_source':False}

    def _invalidate_text_filter_views(self):
        dirty=False
        for sd in self.sheets.values():
            if getattr(sd,'text_filter_applied',False):
                sd.text_filter_applied=False;dirty=True
        if dirty:self.cache.clear()

    def set_value(self, sheet, row, col, value):
        """Edit a cell and invalidate every transitive dependent (SPEC018-style
        propagation: only dirty cells are re-evaluated on next read)."""
        sd = self._sheet(sheet)
        if sd is None:
            raise KeyError(sheet)
        if self.array_output_region(sd.title,row,col) is not None:
            raise ValueError('array-output-edit-unsupported')
        self._invalidate_text_filter_views()
        self._clear_dependencies((sd.title.lower(), row, col))
        sd.formulas.pop((row, col), None)
        sd.cached[(row, col)] = BLANK if value is None else value
        sd.max_row = max(sd.max_row, row)
        sd.max_col = max(sd.max_col, col)
        key = (sd.title.lower(), row, col)
        self._mark_pivot_source_dirty(sd.title,row,col)
        self._invalidate(key)

    def set_formula(self, sheet, row, col, formula_text):
        sd = self._sheet(sheet)
        if sd is None:
            raise KeyError(sheet)
        if self.array_output_region(sd.title,row,col) is not None:
            raise ValueError('array-output-edit-unsupported')
        self._invalidate_text_filter_views()
        self._clear_dependencies((sd.title.lower(), row, col))
        sd.formulas[(row, col)] = formula_text.lstrip("=")
        sd.cached.pop((row, col), None)
        sd.max_row = max(sd.max_row, row)
        sd.max_col = max(sd.max_col, col)
        self._mark_pivot_source_dirty(sd.title,row,col)
        self._invalidate((sd.title.lower(), row, col))

    def _mark_pivot_source_dirty(self,sheet,row,col):
        from openpyxl.utils.cell import range_boundaries
        for p in self.pivot_snapshots:
            bounds=None;source_sheet=p["source_sheet"]
            if p["source_table"] and p["source_table"].lower() in self.tables:
                sl,r1,c1,r2,c2,_,_=self.tables[p["source_table"].lower()]
                source_sheet=sl;bounds=(c1,r1,c2,r2)
            elif p["source_ref"]:
                bounds=range_boundaries(p["source_ref"])
            if bounds and source_sheet and source_sheet.lower()==sheet.lower():
                c1,r1,c2,r2=bounds
                if r1<=row<=r2 and c1<=col<=c2:
                    p["source_dirty"]=True
                    note=f"pivot-source-dirty:{p['sheet']}:{p['name']}; saved display not refreshed"
                    if note not in self.notes:self.notes.append(note)

    def _mark_invalidated_pivot_sources_dirty(self, keys):
        """Check recorded invalidation coordinates in one metadata-bound batch.

        No dependency discovery, pivot refresh or metadata cache. Resolve current
        table/range bounds once per still-clean pivot; skip unrelated sheets.
        """
        from openpyxl.utils.cell import range_boundaries
        by_sheet = {}
        for sheet,row,col in keys:
            by_sheet.setdefault(sheet, []).append((row,col))
        for p in self.pivot_snapshots:
            if p['source_dirty']:
                continue
            bounds=None;source_sheet=p['source_sheet']
            if p['source_table'] and p['source_table'].lower() in self.tables:
                sl,r1,c1,r2,c2,_,_=self.tables[p['source_table'].lower()]
                source_sheet=sl;bounds=(c1,r1,c2,r2)
            elif p['source_ref']:
                bounds=range_boundaries(p['source_ref'])
            if not bounds or not source_sheet:
                continue
            points=by_sheet.get(source_sheet.lower(), ())
            c1,r1,c2,r2=bounds
            if any(r1<=r<=r2 and c1<=c<=c2 for r,c in points):
                p['source_dirty']=True
                note=f"pivot-source-dirty:{p['sheet']}:{p['name']}; saved display not refreshed"
                if note not in self.notes:self.notes.append(note)

    def _invalidate(self, key):
        seen = set()
        stack = [key]
        while stack:
            k = stack.pop()
            if k in seen:
                continue
            seen.add(k)
            self.cache.pop(k, None)
            for dep in self.rdeps.get(k, ()):
                stack.append(dep)
            # dependents whose range reference contains k
            for (r1, c1, r2, c2, dep_key) in self.rdeps_ranges.get(k[0], ()):  #
                if r1 <= k[1] <= r2 and c1 <= k[2] <= c2:
                    stack.append(dep_key)

        if self.pivot_snapshots:
            self._mark_invalidated_pivot_sources_dirty(seen)

    def cell_value_now(self, sheet, row, col, budget_seconds=None):
        """Public read: value with current caches (recalc-on-read)."""
        sd = self._sheet(sheet)
        if sd is None:
            return REF_ERR
        if self._array_follower_refusal(sd,row,col):return NAME_ERR
        root = (sd.title.lower(), row, col)
        if root in self.cache:
            return self.cache[root]
        if (row, col) not in sd.formulas:
            return sd.cached.get((row, col), BLANK)
        # On-demand stack machine: unresolved reads suspend evaluation and add
        # the needed cell. This preserves IF laziness without Python recursion.
        deadline = time.monotonic() + budget_seconds if budget_seconds is not None else None
        pending = [root]
        positions = {root: 0}
        self._scheduler_active = True
        self._range_read_scope = {"ranges":{},"reserved_cells":0}
        try:
            while pending:
                if deadline is not None and time.monotonic() >= deadline:
                    raise CalculationBudgetExceeded(f"suspended root={root}; pending depth={len(pending)}")
                key = pending[-1]
                self.stats["max_dependency_depth"] = max(self.stats["max_dependency_depth"], len(pending))
                if key in self.cache:
                    positions.pop(key, None)
                    pending.pop()
                    continue
                current = self.sheets[key[0]]
                ctx = EvalContext(self, current.title, key[1], key[2], self.today_serial, set())
                try:
                    self._eval_cell(current, key[1], key[2], current.formulas[key[1:]], ctx)
                except _NeedCell as need:
                    dep = need.key
                    self.rdeps.setdefault(dep, set()).add(key)
                    self.deps.setdefault(key, set()).add(dep)
                    if dep in positions:
                        path = pending[positions[dep]:] + [dep]
                        self.cycle_diagnostics.append(path)
                        self.notes.append(f"runtime-cycle:{path}")
                        for member in path:
                            self.cache[member] = ErrorValue("#CIRC!")
                    else:
                        positions[dep] = len(pending)
                        pending.append(dep)
            return self.cache[root]
        finally:
            self._range_read_scope = None
            self._scheduler_active = False


class _DepTracker:
    """Wraps a Workbook during one cell evaluation to record dependencies."""

    def __init__(self, wb, sink):
        self._wb = wb
        self._sink = sink

    def __getattr__(self, name):
        return getattr(self._wb, name)

    def get_value(self, sheet, row, col, ctx):
        sd = self._wb._sheet(sheet)
        if sd is not None:
            self._sink.add((sd.title.lower(), row, col))
        return self._wb.get_value(sheet, row, col, ctx)

    def record_reference(self,ref,ctx):
        sd=self._wb._sheet(ref.sheet or ctx.current_sheet)
        if sd is None or ref.ext is not None:return
        self._sink.add((sd.title.lower(),1 if ref.whole_cols else ref.r1,
                        1 if ref.whole_rows else ref.c1,
                        1048576 if ref.whole_cols else ref.r2,
                        16384 if ref.whole_rows else ref.c2))

    def get_range(self, ref, ctx):
        if ref.ext is not None:
            return self._wb._external_range(ref, ctx)
        sd = self._wb._sheet(ref.sheet or ctx.current_sheet)
        if sd is None:
            return Range(((REF_ERR,),))
        r1, r2 = ref.r1, ref.r2
        c1, c2 = ref.c1, ref.c2
        if ref.whole_cols:
            r1, r2 = 1, sd.max_row
        if ref.whole_rows:
            c1, c2 = 1, sd.max_col
        # Invalidation covers the original legal reference, including currently
        # empty cells. Evaluation may still clamp to the occupied extent.
        self._sink.add((sd.title.lower(), r1, c1,
                        1048576 if ref.whole_cols else r2,
                        16384 if ref.whole_rows else c2))
        r2 = min(r2, max(sd.max_row, r1))
        c2 = min(c2, max(sd.max_col, c1))
        # Local immutable input view during this synchronous public read only.
        # Prefixes survive scheduler suspension, never an edit or next read.
        scope=self._wb._range_read_scope
        size=max(0,r2-r1+1)*max(0,c2-c1+1)
        key=(sd.title.lower(),r1,c1,r2,c2)
        entry=None
        if scope is not None and 0<size<=20000:
            entry=scope['ranges'].get(key)
            if entry is None and len(scope['ranges'])<64 and scope['reserved_cells']+size<=250000:
                entry={'values':[], 'range':None}
                scope['ranges'][key]=entry
                scope['reserved_cells']+=size
        if entry is not None:
            if entry['range'] is not None:return entry['range']
            width=c2-c1+1
            values=entry['values']
            while len(values)<size:
                index=len(values)
                values.append(self._wb.get_value(sd.title,r1+index//width,c1+index%width,ctx))
            rows=tuple(tuple(values[i:i+width]) for i in range(0,size,width))
            result=Range(rows,sheet=sd.title,row0=r1,col0=c1)
            entry['range']=result
            return result
        rows = []
        for r in range(r1, r2 + 1):
            row = []
            for c in range(c1, c2 + 1):
                row.append(self._wb.get_value(sd.title, r, c, ctx))
            rows.append(tuple(row))
        return Range(tuple(rows), sheet=sd.title, row0=r1, col0=c1)
