"""Formula handlers with explicitly scoped semantics.

Registration is not full Excel compatibility. Unsupported modes or shapes
return errors with diagnostic notes; tests and FE-3 define verified scope.
"""
from __future__ import annotations

import datetime
from functools import lru_cache
import math
import re

from .values import (ErrorValue, Range, BLANK, NA, VALUE_ERR, REF_ERR, DIV0,
                     NAME_ERR, NUM_ERR, is_error, is_blank, to_number, to_text,
                     to_bool, compare)


def _flatten(v):
    """Yield scalar values from scalar or Range."""
    if isinstance(v, Range):
        yield from v.iter_values()
    else:
        yield v


def _evargs(args, ctx, array=True):
    """Evaluate raw AST args (or _RawArg) to values, preserving Range shape."""
    out = []
    for a in args:
        if isinstance(a, _RawArg):
            out.append(a.v)
        else:
            out.append(ctx.resolve_arg(a, array=array))
    return out


def _numbers_only(v):
    """Values that participate in SUM-style aggregation: numbers and bools in
    direct args; inside ranges only true numbers count (Excel rule)."""
    if isinstance(v, Range):
        for x in v.iter_values():
            if isinstance(x, (int, float)) and not isinstance(x, bool):
                yield float(x)
            elif is_error(x):
                yield x
    else:
        if isinstance(v, bool):
            yield 1.0 if v else 0.0
        elif isinstance(v, (int, float)):
            yield float(v)
        elif isinstance(v, str):
            n = to_number(v)
            yield n  # may be error
        elif is_blank(v):
            pass
        elif is_error(v):
            yield v


def _wildcard_regex_uncached(text):
    """Excel wildcard text, tilde escapes only *, ? and ~."""
    parts=[];i=0
    while i<len(text):
        c=text[i]
        if c=='~' and i+1<len(text) and text[i+1] in '*?~':
            i+=1;parts.append(re.escape(text[i]))
        elif c=='*':parts.append('.*')
        elif c=='?':parts.append('.')
        else:parts.append(re.escape(c))
        i+=1
    return ''.join(parts)


_WILDCARD_PATTERN_CACHE_MAXSIZE = 1024
_WILDCARD_PATTERN_CACHE_MAX_CHARS = 255


@lru_cache(maxsize=_WILDCARD_PATTERN_CACHE_MAXSIZE)
def _wildcard_regex_cached(text):
    # Pure immutable pattern strings only. Not workbook evaluation results.
    # Private criteria text can remain until eviction/clear; service adapters
    # must decide cache lifecycle and must not log cache keys.
    return _wildcard_regex_uncached(text)


def _wildcard_regex(text):
    # SEARCH/MATCH also call this helper. Preserve overlength behavior without
    # retaining arbitrarily large keys or generated patterns.
    if len(text) > _WILDCARD_PATTERN_CACHE_MAX_CHARS:
        return _wildcard_regex_uncached(text)
    return _wildcard_regex_cached(text)


def _clear_wildcard_pattern_cache():
    """Private lifecycle hook for a future owner-scoped service adapter."""
    _wildcard_regex_cached.cache_clear()


def _criteria_match(value, crit, ctx=None):
    """SUMIF/COUNTIF criteria: number, text (with wildcards * ?), or an
    expression string like "<>TRUE", ">=5", "". Returns bool."""
    if is_error(crit):
        return crit
    if is_blank(value):
        value_cmp = BLANK
    else:
        value_cmp = value
    if isinstance(crit, (int, float)) and not isinstance(crit, bool):
        return _loose_eq(value_cmp, float(crit))
    if isinstance(crit, bool):
        if is_blank(value_cmp):
            return crit is False
        if isinstance(value_cmp, bool):
            return value_cmp == crit
        if isinstance(value_cmp, str):
            return value_cmp.strip().upper() == ("TRUE" if crit else "FALSE")
        return False
    if isinstance(crit, str):
        # Excel's long-criteria behavior is not certified by this prototype.
        if len(crit)>255:
            if ctx is not None:ctx.unsupported.append('criteria:long-text')
            return NAME_ERR
        m = re.match(r"^(<=|>=|<>|=|<|>)(.*)$", crit)
        if m:
            op, rhs = m.group(1), m.group(2)
            if any(c in rhs for c in '*?~'):
                if op not in ('=','<>'):
                    if ctx is not None:ctx.unsupported.append('criteria:relational-wildcard')
                    return NAME_ERR
                if is_error(value_cmp):
                    if ctx is not None:ctx.unsupported.append('criteria:wildcard-error-input')
                    return NAME_ERR
                matched=isinstance(value_cmp,str) and re.fullmatch(_wildcard_regex(rhs),value_cmp,re.I|re.S) is not None
                return matched if op=='=' else not matched
            rhs_v = _parse_criteria_literal(rhs)
            c = compare(value_cmp, rhs_v)
            if is_error(c):
                return False
            return {"=": c == 0, "<>": c != 0, "<": c < 0, "<=": c <= 0, ">": c > 0, ">=": c >= 0}[op]
        # plain text: wildcard match, case-insensitive
        if is_blank(value_cmp):
            return crit == ""
        if not isinstance(value_cmp, str):
            return _loose_eq(value_cmp, _parse_criteria_literal(crit))
        return re.fullmatch(_wildcard_regex(crit),value_cmp,re.I|re.S) is not None
    return False


def _parse_criteria_literal(s):
    s2 = s.strip()
    if s2.upper() == "TRUE":
        return True
    if s2.upper() == "FALSE":
        return False
    try:
        return float(s2)
    except ValueError:
        # Text criteria keep their exact characters: Excel does not trim a trailing space in the criterion, so "<>X " differs from X.
        return s


def _loose_eq(a, b):
    if is_blank(a):
        return b == 0.0 or b == "" or b is False
    if isinstance(a, str) and isinstance(b, (int, float)):
        try:
            return float(a) == b
        except ValueError:
            return False
    if isinstance(a, (int, float)) and isinstance(b, str):
        try:
            return a == float(b)
        except ValueError:
            return False
    if isinstance(a, str) and isinstance(b, str):
        return a.lower() == b.lower()
    return a == b


def _excel_round(x, ndigits, mode="half_away"):
    """Excel ROUND family: half away from zero (not Python banker's)."""
    if ndigits >= 0:
        p = 10.0 ** ndigits
        v = x * p
    else:
        p = 10.0 ** (-ndigits)
        v = x / p
    if mode == "up":      # ROUNDUP: away from zero
        r = math.ceil(abs(v)) if v >= 0 else -math.ceil(abs(-v))
        r = math.copysign(math.ceil(abs(v)), v)
    elif mode == "down":  # ROUNDDOWN / INT-ish truncation toward zero
        r = math.trunc(v)
    else:                 # half away from zero
        f = math.floor(abs(v))
        frac = abs(v) - f
        r = f + (1 if frac >= 0.5 - 1e-12 else 0)
        r = math.copysign(r, v)
    if ndigits >= 0:
        return r / p
    return r * p


def _date_serial(y, m, d):
    base = datetime.date(1899, 12, 30)  # Excel 1900 system incl. leap bug
    return (datetime.date(int(y), int(m), int(d)) - base).days


# ---------------- individual functions ----------------
# Convention: each fn(args, ctx) where ctx gives resolve(RangeRef)->Range etc.
# Range arguments stay as Range objects; scalar args are scalars.

def FN_IF(args, ctx):
    cond = to_bool(ctx.scalar(args[0]))
    if is_error(cond):
        return cond
    if cond:
        return ctx.scalar(args[1]) if len(args) > 1 else True
    return ctx.scalar(args[2]) if len(args) > 2 else False


def FN_IFS(args, ctx):
    for i in range(0, len(args) - 1, 2):
        cond = to_bool(ctx.scalar(args[i]))
        if is_error(cond):
            return cond
        if cond:
            return ctx.scalar(args[i + 1])
    return NA


def FN_IFERROR(args, ctx):
    v = ctx.scalar(args[0], catch_errors=False)
    if is_error(v):
        return ctx.scalar(args[1])
    return v


def FN_IFNA(args, ctx):
    v = ctx.scalar(args[0], catch_errors=False)
    if v == NA:
        return ctx.scalar(args[1])
    return v


def FN_AND(args, ctx):
    result = True
    for a in _evargs(args, ctx):
        for v in _flatten(a):
            if is_error(v):
                return v
            if is_blank(v):
                continue
            b = to_bool(v)
            if is_error(b):
                return b
            result = result and b
    return result


def FN_OR(args, ctx):
    result = False
    for a in _evargs(args, ctx):
        for v in _flatten(a):
            if is_error(v):
                return v
            if is_blank(v):
                continue
            b = to_bool(v)
            if is_error(b):
                return b
            result = result or b
    return result


def FN_NOT(args, ctx):
    b = to_bool(ctx.scalar(args[0]))
    if is_error(b):
        return b
    return not b


def FN_SUM(args, ctx):
    # A direct cell reference retains reference coercion rules even though its
    # resolved value is scalar. Non-numeric reference text/logicals are ignored.
    from .parser import CellRef, RangeRef, TableRef, DynRange, FuncCall
    total = 0.0
    for raw in args:
        a = ctx.resolve_arg(raw, array=True)
        # INDEX(reference,row[,column]) retains reference provenance for SUM.
        # Do not classify computed-array/scalar INDEX inputs as references.
        index_ref = (isinstance(raw, FuncCall)
                     and raw.name.removeprefix('_XLFN.') == 'INDEX'
                     and len(raw.args) in (2, 3)
                     and isinstance(raw.args[0], (CellRef, RangeRef, TableRef, DynRange)))
        if (isinstance(raw, CellRef) or index_ref) and not isinstance(a, Range):
            a = Range(((a,),))
        for v in _numbers_only(a):
            if is_error(v):
                return v
            total += v
    return total


def FN_COUNT(args, ctx):
    # Literal booleans/numeric text count when supplied directly, never when
    # stored in a referenced cell/array. Errors remain ignored, unlike SUM.
    from .parser import Bool, Str
    n = 0
    for raw in args:
        a = ctx.resolve_arg(raw, array=True)
        if isinstance(raw, (Bool, Str)) and not isinstance(a, Range):
            numeric = to_number(a)
            if not is_error(numeric) and math.isfinite(numeric):
                n += 1
            continue
        for v in _flatten(a):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                n += 1
    return float(n)


def FN_COUNTA(args, ctx):
    n = 0
    for a in _evargs(args, ctx):
        for v in _flatten(a):
            if not is_blank(v):
                n += 1
    return float(n)


def FN_COUNTBLANK(args, ctx):
    n = 0
    for raw in args:
        a=ctx.resolve_arg(raw)
        from .parser import DynRange
        if isinstance(raw,DynRange) and is_error(a):return a
        values=list(_flatten(a))
        n+=sum(is_blank(v) or v=="" for v in values)
        logical=ctx.reference_cell_count(raw)
        if logical is not None:
            n+=max(0,logical-len(values))
    return float(n)


def FN_AVERAGE(args, ctx):
    # Direct CellRef text/logical/blank values are ignored, while zero counts.
    # Other expression/returned-reference provenance is not certified here.
    from .parser import CellRef
    vals = []
    for raw in args:
        a = ctx.resolve_arg(raw, array=True)
        if isinstance(raw, CellRef) and not isinstance(a, Range):
            a = Range(((a,),))
        for v in _numbers_only(a):
            if is_error(v):
                return v
            vals.append(v)
    if not vals:
        return DIV0
    return sum(vals) / len(vals)


def _min_max(args, ctx, pick):
    # Direct cells are references, not directly typed text/logical literals.
    # Scope is CellRef only; INDEX/reference-returning provenance is separate.
    from .parser import CellRef
    vals = []
    for raw in args:
        a = ctx.resolve_arg(raw, array=True)
        if isinstance(raw, CellRef) and not isinstance(a, Range):
            a = Range(((a,),))
        for v in _numbers_only(a):
            if is_error(v):
                return v
            vals.append(v)
    if not vals:
        return 0.0
    return pick(vals)


def FN_MAX(args, ctx):
    return _min_max(args, ctx, max)


def FN_MIN(args, ctx):
    return _min_max(args, ctx, min)


def FN_ABS(args, ctx):
    n = to_number(ctx.scalar(args[0]))
    return n if is_error(n) else abs(n)


def FN_INT(args, ctx):
    n = to_number(ctx.scalar(args[0]))
    return n if is_error(n) else float(math.floor(n))


def FN_ROUND(args, ctx):
    n = to_number(ctx.scalar(args[0]))
    d = to_number(ctx.scalar(args[1]))
    if is_error(n):
        return n
    if is_error(d):
        return d
    return _excel_round(n, int(d), "half_away")


def FN_ROUNDUP(args, ctx):
    n = to_number(ctx.scalar(args[0]))
    d = to_number(ctx.scalar(args[1]))
    if is_error(n):
        return n
    if is_error(d):
        return d
    return _excel_round(n, int(d), "up")


def FN_ROUNDDOWN(args, ctx):
    n = to_number(ctx.scalar(args[0]))
    d = to_number(ctx.scalar(args[1]))
    if is_error(n):
        return n
    if is_error(d):
        return d
    return _excel_round(n, int(d), "down")


def FN_SQRT(args, ctx):
    n = to_number(ctx.scalar(args[0]))
    if is_error(n):
        return n
    if n < 0:
        return NUM_ERR
    return math.sqrt(n)


def FN_POWER(args, ctx):
    a = to_number(ctx.scalar(args[0]))
    b = to_number(ctx.scalar(args[1]))
    if is_error(a):
        return a
    if is_error(b):
        return b
    try:
        return a ** b
    except (OverflowError, ZeroDivisionError):
        return NUM_ERR


# ---- text ----

def _text_map(arg,ctx,transform):
    v=ctx.resolve_arg(arg,array=True)
    def apply(x):
        s=to_text(x)
        return s if is_error(s) else transform(s)
    if isinstance(v,Range):
        return Range(tuple(tuple(apply(x) for x in row) for row in v.cells),sheet=v.sheet,row0=v.row0,col0=v.col0)
    return apply(v)


def FN_UPPER(args,ctx):return _text_map(args[0],ctx,str.upper)
def FN_LOWER(args,ctx):return _text_map(args[0],ctx,str.lower)
def FN_TRIM(args,ctx):return _text_map(args[0],ctx,lambda s:re.sub(r" +"," ",s.strip(" ")))
def FN_LEN(args,ctx):return _text_map(args[0],ctx,lambda s:float(len(s)))


def FN_LEFT(args, ctx):
    s = to_text(ctx.scalar(args[0]))
    if is_error(s):
        return s
    n = 1.0
    if len(args) > 1:
        n = to_number(ctx.scalar(args[1]))
        if is_error(n):
            return n
    if n < 0:
        return VALUE_ERR
    return s[:int(n)]


def FN_RIGHT(args, ctx):
    s = to_text(ctx.scalar(args[0]))
    if is_error(s):
        return s
    n = 1.0
    if len(args) > 1:
        n = to_number(ctx.scalar(args[1]))
        if is_error(n):
            return n
    if n < 0:
        return VALUE_ERR
    n = int(n)
    return s[len(s) - n:] if n else ""


def FN_MID(args, ctx):
    s = to_text(ctx.scalar(args[0]))
    start = to_number(ctx.scalar(args[1]))
    n = to_number(ctx.scalar(args[2]))
    if is_error(s):
        return s
    if is_error(start):
        return start
    if is_error(n):
        return n
    if start < 1 or n < 0:
        return VALUE_ERR
    return s[int(start) - 1:int(start) - 1 + int(n)]


def _find_one(needle, haystack, start=1):
    """Excel FIND: case-sensitive, 1-based; returns 0 when absent."""
    pos = haystack.find(needle, start - 1)
    return pos + 1 if pos >= 0 else 0


def FN_FIND(args, ctx):
    needle = to_text(ctx.scalar(args[0]))
    hay = to_text(ctx.scalar(args[1]))
    if is_error(needle):
        return needle
    if is_error(hay):
        return hay
    start = 1
    if len(args) > 2:
        start = to_number(ctx.scalar(args[2]))
        if is_error(start):
            return start
    p = _find_one(needle, hay, int(start))
    return float(p) if p else VALUE_ERR


def FN_SEARCH(args, ctx):
    if len(args) not in (2,3):return VALUE_ERR
    needle=to_text(ctx.scalar(args[0]));hay=to_text(ctx.scalar(args[1]))
    if is_error(needle):return needle
    if is_error(hay):return hay
    start=to_number(ctx.scalar(args[2])) if len(args)>2 else 1
    if is_error(start):return start
    if not math.isfinite(start):return VALUE_ERR
    start=math.trunc(start)
    if start<1 or start>len(hay):return VALUE_ERR
    m=re.search(_wildcard_regex(needle),hay[start-1:],re.I|re.S)
    return float(m.start()+start) if m else VALUE_ERR


def FN_SUBSTITUTE(args, ctx):
    text = to_text(ctx.scalar(args[0]))
    old = to_text(ctx.scalar(args[1]))
    new = to_text(ctx.scalar(args[2]))
    if is_error(text):
        return text
    if is_error(old):
        return old
    if is_error(new):
        return new
    if old == "":
        return text
    if len(args) > 3:
        inst = to_number(ctx.scalar(args[3]))
        if is_error(inst):
            return inst
        inst = int(inst)
        parts = text.split(old)
        if inst < 1 or inst >= len(parts):
            return text
        out = parts[0]
        for i, part in enumerate(parts[1:], 1):
            out += (new if i == inst else old) + part
        return out
    return text.replace(old, new)


def FN_CONCATENATE(args, ctx):
    out = []
    for a in _evargs(args, ctx):
        for v in _flatten(a):
            s = to_text(v)
            if is_error(s):
                return s
            out.append(s)
    return "".join(out)


def FN_EXACT(args, ctx):
    a = to_text(ctx.scalar(args[0]))
    b = to_text(ctx.scalar(args[1]))
    if is_error(a):
        return a
    if is_error(b):
        return b
    return a == b


def FN_VALUE(args, ctx):
    v = ctx.scalar(args[0])
    if isinstance(v, (int, float)):
        return float(v)
    n = to_number(v)
    return n


def FN_NUMBERVALUE(args, ctx):
    """Explicit separator conversion; omitted separators use caller config.

    This does not infer source-workbook locale. Compatibility defaults remain
    decimal dot/group comma unless the caller supplies different separators.
    """
    from .parser import Empty
    if not 1<=len(args)<=3:return VALUE_ERR
    s=to_text(ctx.scalar(args[0]))
    if is_error(s):return s
    dec=getattr(ctx.workbook,'number_decimal_separator','.')
    grp=getattr(ctx.workbook,'number_group_separator',',')
    if len(args)>1 and not isinstance(args[1],Empty):
        dec=to_text(ctx.scalar(args[1]))
        if is_error(dec):return dec
        dec=dec[:1]
    if len(args)>2 and not isinstance(args[2],Empty):
        grp=to_text(ctx.scalar(args[2]))
        if is_error(grp):return grp
        grp=grp[:1]
    if not dec or dec==' ':
        ctx.unsupported.append('numbervalue:empty-or-space-decimal-separator')
        return NAME_ERR
    if dec==grp:return VALUE_ERR
    if dec.isalnum() or (grp and grp.isalnum()) or any(c in '+-%' for c in dec+grp):
        ctx.unsupported.append('numbervalue:unverified-separator')
        return NAME_ERR
    t=s.replace(' ','')
    if not t:return 0.0
    percent=len(t)-len(t.rstrip('%'));t=t.rstrip('%')
    if t.count(dec)>1:return VALUE_ERR
    if dec in t:
        left,right=t.split(dec)
        if grp and grp in right:return VALUE_ERR
    else:left,right=t,None
    if grp:left=left.replace(grp,'')
    t=left+('.'+right if right is not None else '')
    if not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?',t):return VALUE_ERR
    try:v=float(t)*(0.01**percent)
    except (ValueError,OverflowError):return VALUE_ERR
    if not math.isfinite(v):
        ctx.unsupported.append('numbervalue:numeric-overflow')
        return NAME_ERR
    return v


def FN_TEXT(args, ctx):
    """Scoped fixed numeric formatting, not a general Excel format interpreter.

    Dot-decimal/comma-group output, zero placeholders, optional dollar prefix
    and percent suffix only. Locale/date/section/color/scientific codes reject.
    """
    from decimal import Decimal,localcontext,ROUND_HALF_UP,InvalidOperation
    if len(args)!=2:return VALUE_ERR
    v=ctx.resolve_arg(args[0],array=True)
    if isinstance(v,Range):
        return Range(tuple(tuple(FN_TEXT([_RawArg(x),args[1]],ctx) for x in row) for row in v.cells),sheet=v.sheet,row0=v.row0,col0=v.col0)
    fmt=to_text(ctx.scalar(args[1]))
    if is_error(fmt):return fmt
    if is_error(v):return v
    if isinstance(v,str):
        try:v=float(v)
        except ValueError:return v
    if is_blank(v):v=0.0
    if isinstance(v,bool):return 'TRUE' if v else 'FALSE'
    if fmt.upper()=='GENERAL':return to_text(v)
    m=re.fullmatch(r'(\$|"\$"|)(#,##0|0+)(\.0+)?(%)?',fmt)
    if not m:
        ctx.unsupported.append('text:format-code')
        return NAME_ERR
    prefix='$' if m.group(1) else ''
    integer=m.group(2);nd=len(m.group(3))-1 if m.group(3) else 0
    if not math.isfinite(v) or abs(v)>=1e15 or nd>15 or len(integer)>32:
        ctx.unsupported.append('text:numeric-format-budget')
        return NAME_ERR
    try:
        with localcontext() as dc:
            dc.prec=50
            d=Decimal(str(v))*(100 if m.group(4) else 1)
            d=d.quantize(Decimal(1).scaleb(-nd),rounding=ROUND_HALF_UP)
            if not d:d=abs(d)  # suppress negative rounded zero, secondary fixture
            s=format(d,(',' if ',' in integer else '')+'.'+str(nd)+'f')
    except (InvalidOperation,ValueError):
        ctx.unsupported.append('text:numeric-format')
        return NAME_ERR
    if ',' not in integer and len(integer)>1:
        sign='-' if s.startswith('-') else ''
        raw=s.lstrip('-');whole,dot,fraction=raw.partition('.')
        s=sign+whole.zfill(len(integer))+(dot+fraction if dot else '')
    if prefix and s.startswith('-'):s='-'+prefix+s[1:]
    else:s=prefix+s
    return s+('%' if m.group(4) else '')


# ---- information ----

def FN_ISERROR(args, ctx):
    return is_error(ctx.scalar(args[0], catch_errors=False))


def FN_ISNA(args, ctx):
    return ctx.scalar(args[0], catch_errors=False) == NA


def FN_ISBLANK(args, ctx):
    return is_blank(ctx.scalar(args[0]))


def FN_ISNUMBER(args, ctx):
    v = ctx.scalar(args[0])
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def FN_ISTEXT(args, ctx):
    return isinstance(ctx.scalar(args[0]), str)


def FN_ISLOGICAL(args, ctx):
    return isinstance(ctx.scalar(args[0]), bool)


def FN_NA(args, ctx):
    return NA


def FN_ROW(args, ctx):
    if not args:
        return float(ctx.current_row)
    a = args[0]
    from .parser import CellRef, RangeRef
    if isinstance(a, CellRef):
        return float(a.row)
    if isinstance(a, RangeRef):
        first=a.r1 if a.r1 is not None else 1
        if getattr(ctx,'_function_array_context',False):
            last=1048576 if a.whole_cols else a.r2
            if last-first+1>200000:
                ctx.unsupported.append('row:array-budget');return NAME_ERR
            return Range(tuple((float(r),) for r in range(first,last+1)))
        return float(first)
    return VALUE_ERR


def FN_COLUMN(args, ctx):
    if not args:
        return float(ctx.current_col)
    a = args[0]
    from .parser import CellRef, RangeRef
    if isinstance(a, CellRef):
        return float(a.col)
    if isinstance(a, RangeRef):
        first=a.c1 if a.c1 is not None else 1
        if getattr(ctx,'_function_array_context',False):
            last=16384 if a.whole_rows else a.c2
            return Range((tuple(float(c) for c in range(first,last+1)),))
        return float(first)
    return VALUE_ERR


# ---- lookup ----

def _range_arg(a, ctx):
    r = ctx.resolve_arg(a)
    if isinstance(r, Range):
        return r
    return Range(((r,),))


def FN_INDEX(args, ctx):
    """Both INDEX forms used in corpus:
    INDEX(range, row) / INDEX(range, row, col) with 0 meaning whole row/col.
    Also INDEX(array-computation-result, n) where the first arg is an inline
    array produced by arithmetic on ranges (array semantics).
    """
    rn = to_number(ctx.scalar(args[1])) if len(args) > 1 else 1.0
    if is_error(rn):
        return rn
    cn = 1.0
    if len(args) > 2:
        cn = to_number(ctx.scalar(args[2]))
        if is_error(cn):
            return cn
    handled, result = ctx.index_reference(args[0], rn, cn, len(args))
    if handled:
        return result
    target = ctx.resolve_arg(args[0],array=True)
    if is_error(target):
        return target
    if isinstance(target, Range):
        cells = target.cells
        nrows, ncols = target.nrows, target.ncols
        ri, ci = int(rn), int(cn)
        if ri == 0 and ci == 0:
            return target
        if nrows == 1 and ncols > 1 and len(args) == 2:
            ri, ci = 1, int(rn)
        elif ncols == 1 and len(args) == 2:
            ri, ci = int(rn), 1
        if ri == 0:  # whole column slice -> Range
            return Range(tuple(tuple(row[ci - 1] for _ in (0,)) for row in cells)) if 1 <= ci <= ncols else REF_ERR
        if ci == 0:
            if 1 <= ri <= nrows:
                return Range((cells[ri - 1],))
            return REF_ERR
        if 1 <= ri <= nrows and 1 <= ci <= ncols:
            v = cells[ri - 1][ci - 1]
            return 0.0 if is_blank(v) else v
        return REF_ERR
    # scalar
    if int(rn) in (0, 1) and int(cn) in (0, 1):
        return target
    return REF_ERR


def _match_exact(lookup, values):
    """Exact match with wildcard support for text. Returns 1-based index or None."""
    if isinstance(lookup, str) and any(c in lookup for c in '*?~'):
        pat = _wildcard_regex(lookup)
        for i, v in enumerate(values):
            if isinstance(v, str) and re.fullmatch(pat,v,re.I|re.S):
                return i + 1
        return None
    for i, v in enumerate(values):
        # Lookup arrays skip physically empty cells. Comparison operators keep
        # their separate blank-coercion rules; do not reuse them blindly here.
        if is_error(v) or is_blank(v):
            continue
        c = compare(v, lookup)
        if not is_error(c) and c == 0:
            return i + 1
    return None


def FN_MATCH(args, ctx):
    lookup = ctx.resolve_arg(args[0],array=True) if getattr(ctx,'_function_array_context',False) else ctx.scalar(args[0])
    if is_error(lookup):
        return lookup
    target = ctx.resolve_arg(args[1])
    if is_error(target):
        return target
    if not isinstance(target, Range):
        target = Range(((target,),))
    mtype = 1
    if len(args) > 2:
        mtype = to_number(ctx.scalar(args[2]))
        if is_error(mtype):
            return mtype
        mtype = int(mtype)
    values = list(target.iter_values())
    if isinstance(lookup,Range):
        if mtype!=0:
            ctx.unsupported.append('match:approximate-array-lookup')
            return NAME_ERR
        def one(v):
            if is_error(v):return v
            i=_match_exact(v,values)
            return float(i) if i else NA
        return Range(tuple(tuple(one(v) for v in row) for row in lookup.cells),
                     sheet=lookup.sheet,row0=lookup.row0,col0=lookup.col0)
    if mtype == 0:
        i = _match_exact(lookup, values)
        return float(i) if i else NA
    if mtype in (1, -1):
        # approximate: requires sorted data; Excel scans linearly with its rules.
        best = None
        if mtype == 1:
            for i, v in enumerate(values):
                if is_error(v) or isinstance(v, (str, bool)) or is_blank(v):
                    continue
                if v <= lookup:
                    best = i + 1
                else:
                    break
        else:
            for i, v in enumerate(values):
                if is_error(v) or isinstance(v, (str, bool)) or is_blank(v):
                    continue
                if v >= lookup:
                    best = i + 1
                else:
                    break
        return float(best) if best else NA
    return VALUE_ERR


def _exact_reference_table_lookup(args,ctx,horizontal=False):
    """Selected-read path for exact direct/table lookup, not approximate modes.

    Preserve the existing exact-key comparison helper. Only fetch the first
    column/row and selected return cell, avoiding unrelated false cycles.
    """
    from .parser import RangeRef,TableRef
    if len(args) not in (3,4):return True,VALUE_ERR
    # Absent mode means approximate lookup. Leave it to the legacy handler.
    if len(args)<4:return False,None
    exact=to_bool(ctx.scalar(args[3]))
    if is_error(exact):return True,exact
    if exact:return False,None
    ref=ctx.resolve_table(args[1],return_reference=True) if isinstance(args[1],TableRef) else args[1]
    if not isinstance(ref,RangeRef) or ref.whole_rows:return False,None
    if ref.ext is not None and ref.whole_cols:return False,None
    index=to_number(ctx.scalar(args[2]))
    if is_error(index):return True,index
    if not math.isfinite(index):return True,VALUE_ERR
    index=int(index)
    shape=ctx.reference_shape(ref)
    if index<1:return True,VALUE_ERR
    if index>shape[0 if horizontal else 1]:return True,REF_ERR
    lookup=ctx.scalar(args[0])
    if is_error(lookup):return True,lookup
    r1=1 if ref.whole_cols else ref.r1
    r2=1048576 if ref.whole_cols else ref.r2
    first=RangeRef(ref.sheet,ref.ext,r1,ref.c1,r1 if horizontal else r2,
                   ref.c2 if horizontal else ref.c1)
    # A full column's logical geometry is preserved for future growth, while
    # local range materialization remains bounded by occupied rows.
    arr=ctx.resolve_arg(first)
    if is_error(arr):return True,arr
    if not isinstance(arr,Range):return True,VALUE_ERR
    found=_match_exact(lookup,list(arr.iter_values()))
    if found is None:return True,NA
    ri,ci=(index,found) if horizontal else (found,index)
    handled,result=ctx.index_reference(ref,ri,ci,3)
    return (True,result) if handled else (False,None)


def FN_VLOOKUP(args, ctx):
    handled,result=_exact_reference_table_lookup(args,ctx)
    if handled:return result
    lookup = ctx.scalar(args[0])
    if is_error(lookup):
        return lookup
    table = ctx.resolve_arg(args[1])
    if is_error(table):
        return table
    if not isinstance(table, Range):
        return VALUE_ERR
    ci = to_number(ctx.scalar(args[2]))
    if is_error(ci):
        return ci
    ci = int(ci)
    approx = True
    if len(args) > 3:
        b = ctx.scalar(args[3])
        if isinstance(b, bool):
            approx = b
        else:
            bb = to_bool(b)
            if is_error(bb):
                return bb
            approx = bb
    if ci < 1 or ci > table.ncols:
        return REF_ERR
    first_col = [row[0] for row in table.cells]
    if approx:
        best = None
        for i, v in enumerate(first_col):
            if is_error(v) or is_blank(v) or isinstance(v, (str, bool)):
                continue
            lv = lookup
            if isinstance(lv, str):
                try:
                    lv = float(lv)
                except ValueError:
                    break
            if v <= lv:
                best = i
        if best is None:
            return NA
        v = table.cells[best][ci - 1]
        return 0.0 if is_blank(v) else v  # Excel returns 0 for empty lookup cells
    idx = _match_exact(lookup, first_col)
    if idx is None:
        return NA
    v = table.cells[idx - 1][ci - 1]
    return 0.0 if is_blank(v) else v


def FN_HLOOKUP(args, ctx):
    handled,result=_exact_reference_table_lookup(args,ctx,True)
    if handled:return result
    lookup = ctx.scalar(args[0])
    if is_error(lookup):
        return lookup
    table = ctx.resolve_arg(args[1])
    if not isinstance(table, Range):
        return VALUE_ERR
    ri = to_number(ctx.scalar(args[2]))
    if is_error(ri):
        return ri
    ri = int(ri)
    approx = True
    if len(args) > 3:
        b = ctx.scalar(args[3])
        approx = to_bool(b) if not isinstance(b, bool) else b
        if is_error(approx):
            return approx
    if ri < 1 or ri > table.nrows:
        return REF_ERR
    first_row = list(table.cells[0])
    if approx:
        best = None
        for i, v in enumerate(first_row):
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v <= lookup:
                best = i
        if best is None:
            return NA
        v = table.cells[ri - 1][best]
        return 0.0 if is_blank(v) else v
    idx = _match_exact(lookup, first_row)
    if idx is None:
        return NA
    v = table.cells[ri - 1][idx - 1]
    return 0.0 if is_blank(v) else v


def _lookup_canonical_lastrow(args,ctx):
 from .parser import Num,Str,RangeRef,BinOp,FuncCall
 if len(args)!=3 or not isinstance(args[0],Num) or args[0].v!=2:return None
 div=args[1];rv=args[2]
 if not isinstance(div,BinOp) or div.op!='/' or not isinstance(div.l,Num) or div.l.v!=1:return None
 cmp=div.r
 if not isinstance(cmp,BinOp) or cmp.op!='<>' or not isinstance(cmp.r,Str) or cmp.r.v!='':return None
 ref=cmp.l
 if not isinstance(ref,RangeRef) or ref.ext is not None or not ref.whole_cols or ref.whole_rows or ref.c1!=ref.c2:return None
 if not isinstance(rv,FuncCall) or rv.name!='ROW' or len(rv.args)!=1 or not isinstance(rv.args[0],RangeRef):return None
 rr=rv.args[0]
 if rr.ext is not None or not rr.whole_cols or rr.whole_rows or rr.c1!=rr.c2 or rr.c1!=ref.c1:return None
 if (rr.sheet or ctx.current_sheet).lower()!=(ref.sheet or ctx.current_sheet).lower():return None
 # resolve_arg computes only the occupied prefix, recording the original full
 # range dependency through the standard range accessor. ROW is symbolic here.
 ctx.workbook.record_reference(rr,ctx)
 values=ctx.resolve_arg(div,array=True)
 if is_error(values):return values
 if not isinstance(values,Range):return NA
 best=None
 for i,v in enumerate(values.iter_values()):
  if type(v) in (int,float) and v<=2:best=i
 return NA if best is None else float(best+1)


def FN_LOOKUP(args, ctx):
    lastrow=_lookup_canonical_lastrow(args,ctx)
    if lastrow is not None:return lastrow
    lookup = ctx.scalar(args[0])
    if is_error(lookup):
        return lookup
    lv = ctx.resolve_arg(args[1])
    if not isinstance(lv, Range):
        lv = Range(((lv,),))
    rv = ctx.resolve_arg(args[2]) if len(args) > 2 else lv
    if not isinstance(rv, Range):
        rv = Range(((rv,),))
    vals = list(lv.iter_values())
    rvals = list(rv.iter_values())
    best = None
    for i, v in enumerate(vals):
        if is_error(v) or is_blank(v) or isinstance(v, (str, bool)):
            continue
        lv2 = lookup
        if isinstance(lv2, str):
            try:
                lv2 = float(lv2)
            except ValueError:
                continue
        if v <= lv2:
            best = i
    if best is None or best >= len(rvals):
        return NA
    return rvals[best]


# ---- conditional aggregation ----

def _criteria_pairs(args, ctx, sum_range_first):
    """Returns (sum_range_or_None, [(range, criterion), ...])."""
    idx = 0
    sum_range = None
    if sum_range_first:
        sum_range = ctx.resolve_arg(args[0])
        idx = 1
    pairs = []
    while idx < len(args):
        r = ctx.resolve_arg(args[idx])
        c = ctx.scalar(args[idx + 1])
        pairs.append((r, c))
        idx += 2
    return sum_range, pairs


def _agg_rows(pairs,ctx=None):
    """Row indices where all criteria match. Ranges must share shape."""
    base = pairs[0][0]
    if not isinstance(base, Range):
        base = Range(((base,),))
    out = []
    for ri in range(base.nrows):
        for ci in range(base.ncols):
            ok = True
            for r, crit in pairs:
                rr = r if isinstance(r, Range) else Range(((r,),))
                v = rr.cells[ri][ci] if ri < rr.nrows and ci < rr.ncols else BLANK
                m = _criteria_match(v, crit,ctx)
                if is_error(m):
                    return m
                if not m:
                    ok = False
                    break
            if ok:
                out.append((ri, ci))
    return out


def FN_SUMIFS(args, ctx):
    if len(args)<3 or len(args)%2==0:return VALUE_ERR
    _, pairs = _criteria_pairs(args[1:], ctx, False)
    pairs=ctx.aggregation_extent(args[0],args[1::2],pairs)
    if is_error(pairs):return pairs
    hits = _agg_rows(pairs,ctx)
    if is_error(hits):
        return hits
    total = 0.0
    for v in ctx.selected_values(args[0], hits):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            total += v
        elif is_error(v):
            return v
    return total


def FN_COUNTIFS(args, ctx):
    if len(args)%2:return VALUE_ERR
    from .parser import DynRange
    from .evaluator import _dynamic_reference
    for raw in args[::2]:
        if isinstance(raw,DynRange):
            ref = _dynamic_reference(raw,ctx)
            if is_error(ref):return ref
    _, pairs = _criteria_pairs(args, ctx, False)
    shapes=[ctx.reference_shape(a) for a in args[::2]]
    if shapes and all(s is not None for s in shapes):
        if any(s!=shapes[0] for s in shapes):return VALUE_ERR
        logical_rows,logical_cols=shapes[0]
        actual_rows=max((r.nrows if isinstance(r,Range) else 1 for r,c in pairs),default=0)
        actual_cols=max((r.ncols if isinstance(r,Range) else 1 for r,c in pairs),default=0)
        # Scan only occupied union, then analytically count the common empty tail.
        empty=logical_rows*logical_cols-actual_rows*actual_cols
        if empty>0 and any(isinstance(crit,(int,float)) and not isinstance(crit,bool) and crit==0 for r,crit in pairs):
            # Numeric-zero vs blank coercion has conflicting secondary-oracle
            # behavior. Do not extrapolate the generic comparison helper.
            ctx.unsupported.append("countifs:numeric-zero-empty-tail")
            return NAME_ERR
        n=0
        for ri in range(actual_rows):
            for ci in range(actual_cols):
                matches=[]
                for r,crit in pairs:
                    rr=r if isinstance(r,Range) else Range(((r,),))
                    value=rr.cells[ri][ci] if ri<rr.nrows and ci<rr.ncols else BLANK
                    m=_criteria_match(value,crit,ctx)
                    if is_error(m):return m
                    matches.append(m)
                n+=all(matches)
        empty=logical_rows*logical_cols-actual_rows*actual_cols
        tail_matches=[_criteria_match(BLANK,crit,ctx) for r,crit in pairs]
        for m in tail_matches:
            if is_error(m):return m
        if all(tail_matches):n+=max(0,empty)
        return float(n)
    # A computed array's occupied shape cannot establish the original logical
    # range or its blank tail. Do not return a plausible occupied-only count.
    ctx.unsupported.append('countifs:unknown-reference-geometry')
    return NAME_ERR


def FN_AVERAGEIFS(args, ctx):
    if len(args)<3 or len(args)%2==0:return VALUE_ERR
    _, pairs = _criteria_pairs(args[1:], ctx, False)
    pairs=ctx.aggregation_extent(args[0],args[1::2],pairs)
    if is_error(pairs):return pairs
    hits = _agg_rows(pairs,ctx)
    if is_error(hits):
        return hits
    vals = []
    for v in ctx.selected_values(args[0], hits):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            vals.append(v)
        elif is_error(v):
            return v
    return sum(vals) / len(vals) if vals else DIV0


def FN_SUMIF(args, ctx):
    # SUMIF aligns sum_range's top-left to criteria range dimensions, unlike
    # SUMIFS which requires equal declared shapes. Keep selected reads lazy.
    from .parser import CellRef,RangeRef,TableRef,DynRange
    from .evaluator import _dynamic_reference
    if len(args) not in (2,3):return VALUE_ERR
    def ref(a):
        if isinstance(a,DynRange):return _dynamic_reference(a,ctx)
        a=ctx.resolve_table(a,return_reference=True) if isinstance(a,TableRef) else a
        if isinstance(a,CellRef):return RangeRef(a.sheet,a.ext,a.row,a.col,a.row,a.col)
        return a
    criteria=ref(args[0]);summed=ref(args[2]) if len(args)>2 else criteria
    if is_error(criteria):return criteria
    if is_error(summed):return summed
    shape=ctx.reference_shape(criteria)
    if isinstance(criteria,RangeRef) and isinstance(summed,RangeRef) and shape:
        r1=1 if summed.whole_cols else summed.r1;c1=1 if summed.whole_rows else summed.c1
        r2=r1+shape[0]-1;c2=c1+shape[1]-1
        if r2>1048576 or c2>16384:return REF_ERR
        aligned=RangeRef(summed.sheet,summed.ext,r1,c1,r2,c2)
        return FN_SUMIFS([aligned,criteria,args[1]],ctx)
    # Non-reference computed-array shapes are not certified here.
    ctx.unsupported.append('sumif:computed-reference-shape')
    return NAME_ERR


def FN_COUNTIF(args, ctx):
    return FN_COUNTIFS(args,ctx)


class _RawArg:
    """Wraps an already-resolved value so ctx.scalar/resolve_arg return it."""
    __slots__ = ("v",)

    def __init__(self, v):
        self.v = v


_BLANK_FALSE_PREDICATES={"ISERROR","ISNA","ISNUMBER","ISTEXT","ISLOGICAL"}


def _sumproduct_clipped_expression(node,ctx):
    """A computed expression cannot extrapolate transformed missing blank tails."""
    from .parser import Node,RangeRef,TableRef,DynRange,FuncCall
    # ISERROR/ISNA/ISNUMBER/ISTEXT/ISLOGICAL give a constant FALSE for every blank cell, so a blank tail beyond the used rows
    # contributes exactly 0 whatever its length: no extrapolation is needed and Excel returns the same number. ISBLANK is not
    # here: it is TRUE on blanks, so the tail length would matter.
    if isinstance(node,FuncCall) and node.name.removeprefix('_XLFN.').upper() in _BLANK_FALSE_PREDICATES:return False
    if isinstance(node,TableRef):node=ctx.resolve_table(node,return_reference=True)
    if isinstance(node,DynRange):
        from .evaluator import _dynamic_reference
        node = _dynamic_reference(node, ctx)
        if is_error(node):return True
    if isinstance(node,RangeRef):
        if node.ext is not None:return True
        sd=ctx.workbook._sheet(node.sheet or ctx.current_sheet)
        if sd is None:return True
        rows,cols=ctx.reference_shape(node)
        r1=1 if node.whole_cols else node.r1;c1=1 if node.whole_rows else node.c1
        return rows>max(1,sd.max_row-r1+1) or cols>max(1,sd.max_col-c1+1)
    if isinstance(node,FuncCall) and node.name.removeprefix('_XLFN.')=='INDEX':
        # A scalar selection does not inherit its input's unused blank tail.
        # Zero row/column selectors return arrays and must be checked.
        rn=ctx.scalar(node.args[1]) if len(node.args)>1 else 1
        cn=ctx.scalar(node.args[2]) if len(node.args)>2 else 1
        if not is_error(rn) and not is_error(cn) and rn!=0 and cn!=0:return False
    if isinstance(node,Node):
        for field in node.__slots__:
            v=getattr(node,field)
            children=v if isinstance(v,(list,tuple)) else [v]
            if any(_sumproduct_clipped_expression(c,ctx) for c in children if isinstance(c,Node)):return True
    return False


def _sumproduct_guarded_whole_column_args(args,ctx):
    """Bound a zero-tail direct column plus same-sheet pure comparison arrays.

    Scalar CellRef leaves remain eligible (including other local sheets), but
    external scalar refs and all unlisted AST forms retain the old fallback.
    Record original logical ranges before reading the bounded prefix.
    """
    from .parser import RangeRef,CellRef,Num,Str,Bool,Err,Empty,UnOp,BinOp
    direct=[a for a in args if isinstance(a,RangeRef)]
    if not direct:return None
    sd=ctx.workbook._sheet(direct[0].sheet or ctx.current_sheet)
    if sd is None:return None
    refs=[]
    def convert(a):
        if isinstance(a,RangeRef):
            other=ctx.workbook._sheet(a.sheet or ctx.current_sheet)
            if a.ext is not None or other is not sd or not a.whole_cols or a.whole_rows or a.c1!=a.c2:raise ValueError
            refs.append(a)
            return RangeRef(a.sheet,None,1,a.c1,max(1,sd.max_row),a.c2)
        if isinstance(a,CellRef):
            if a.ext is not None:raise ValueError
            return a
        if isinstance(a,(Num,Str,Bool,Err,Empty)):return a
        if isinstance(a,UnOp) and a.op in ('+','-'):return UnOp(a.op,convert(a.x))
        if isinstance(a,BinOp) and a.op in ('=','<>','<','<=','>','>='):return BinOp(a.op,convert(a.l),convert(a.r))
        raise ValueError
    result=[]
    try:
        for a in args:
            before=len(refs);result.append(convert(a))
            if len(refs)==before:raise ValueError
    except ValueError:return None
    for ref in refs:ctx.workbook.record_reference(ref,ctx)
    return result


def FN_SUMPRODUCT(args, ctx):
    """Same-shape arguments; nonnumeric array entries are zero, not coerced.

    Arithmetic inside one argument still uses the evaluator's array operators.
    Direct reference blank tails can be padded with zeros after shape checks.
    """
    if not 1<=len(args)<=255:return VALUE_ERR
    bounded=_sumproduct_guarded_whole_column_args(args,ctx)
    if bounded is not None:args=bounded
    arrays=[];shapes=[]
    for arg in args:
        from .parser import DynRange
        if isinstance(arg,DynRange):
            from .evaluator import _dynamic_reference
            ref = _dynamic_reference(arg,ctx)
            if is_error(ref):return ref
        if ctx.reference_shape(arg) is None and _sumproduct_clipped_expression(arg,ctx):
            ctx.unsupported.append('sumproduct:computed-blank-tail')
            return NAME_ERR
        v=ctx.resolve_arg(arg,array=True)
        if is_error(v):return v
        if not isinstance(v,Range):v=Range(((v,),))
        arrays.append(v)
        shapes.append(ctx.reference_shape(arg) or (v.nrows,v.ncols))
    if any(s!=shapes[0] for s in shapes):return VALUE_ERR
    nrows=max(v.nrows for v in arrays);ncols=max(v.ncols for v in arrays)
    if nrows*ncols>2000000:
        ctx.unsupported.append('sumproduct:occupied-scan-budget')
        return NAME_ERR
    total=0.0
    for ri in range(nrows):
        for ci in range(ncols):
            prod=1.0
            for arr in arrays:
                v=arr.cells[ri][ci] if ri<arr.nrows and ci<arr.ncols else BLANK
                if is_error(v):return v
                n=v if isinstance(v,(int,float)) and not isinstance(v,bool) else 0.0
                prod*=n
            total+=prod
    return total


def FN_SUBTOTAL(args, ctx):
    code = to_number(ctx.scalar(args[0]))
    if is_error(code):
        return code
    code = int(code)
    if code not in tuple(range(1,12))+tuple(range(101,112)):
        ctx.unsupported.append(f"subtotal-code:{code}")
        return VALUE_ERR
    fn = code % 100
    values = []
    for arg in args[1:]:
        subset = ctx.subtotal_values(arg,code)
        if subset is None:
            return VALUE_ERR
        values.extend(subset)
    if fn == 3:
        return float(sum(not is_blank(v) for v in values))
    if fn != 2:
        for v in values:
            if is_error(v):
                return v
    nums = [v for v in values if isinstance(v,(int,float)) and not isinstance(v,bool)]
    if fn in (6,7,8,10,11):
        # Secondary engines treat reference logical values differently. Keep
        # that typed boundary explicit rather than count or ignore by guess.
        if any(type(v)is bool for v in values):
            ctx.unsupported.append('subtotal-statistical-reference-logical-unverified')
            return VALUE_ERR
        try:
            if not all(math.isfinite(v)for v in nums):
                ctx.unsupported.append('subtotal-statistical-nonfinite-input')
                return VALUE_ERR
            if fn==6:result=math.prod(nums)if nums else 0.0
            else:
                # The secondary oracle diverges at extreme squared magnitudes.
                # Refuse this unverified domain rather than silently inherit it.
                if any(v!=0 and not 1e-150<=abs(v)<=1e150 for v in nums):
                    ctx.unsupported.append('subtotal-statistical-extreme-magnitude-unverified')
                    return VALUE_ERR
                import statistics
                if len(nums)<(2 if fn in(7,10)else 1):return DIV0
                operation={7:statistics.stdev,8:statistics.pstdev,10:statistics.variance,11:statistics.pvariance}[fn]
                result=operation(nums)
            return result if math.isfinite(result)else NUM_ERR
        except (OverflowError,ValueError):
            return NUM_ERR
    if fn == 9:return sum(nums)
    if fn == 1:return sum(nums)/len(nums) if nums else DIV0
    if fn == 2:return float(len(nums))
    if fn == 4:return max(nums) if nums else 0.0
    if fn == 5:return min(nums) if nums else 0.0
    return VALUE_ERR


# ---- date ----

def FN_TODAY(args, ctx):
    if args:return VALUE_ERR
    if getattr(ctx.workbook,'date_system_1904',False):
        ctx.unsupported.append('today:1904-date-system')
        return NAME_ERR
    return float(ctx.today_serial)


def FN_NOW(args, ctx):
    # Only a frozen date is injected, not a verified time-of-day clock.
    ctx.unsupported.append('now:no-time-of-day-clock')
    return NAME_ERR


def FN_WORKDAY(args,ctx):
    """Numeric serials >=61 in 1900 system; no text-date/1904 certification."""
    if len(args) not in (2,3):return VALUE_ERR
    if getattr(ctx.workbook,'date_system_1904',False):
        ctx.unsupported.append('workday:1904-date-system')
        return NAME_ERR
    start=to_number(ctx.scalar(args[0]));days=to_number(ctx.scalar(args[1]))
    for v in (start,days):
        if is_error(v):return v
        if not math.isfinite(v):return NUM_ERR
    start=math.trunc(start);days=math.trunc(days)
    if start<0 or start>2958465:return NUM_ERR
    if start<61:
        ctx.unsupported.append('workday:early-1900-serial')
        return NAME_ERR
    if abs(days)>36600:
        ctx.unsupported.append('workday:iteration-budget')
        return NAME_ERR
    holidays=set()
    if len(args)==3:
        value=ctx.resolve_arg(args[2])
        for v in _flatten(value):
            if is_error(v):return v
            if is_blank(v) or v=='':continue
            n=to_number(v)
            if is_error(n):return n
            if not math.isfinite(n):return NUM_ERR
            if n<61:
                ctx.unsupported.append('workday:early-1900-holiday')
                return NAME_ERR
            holidays.add(math.trunc(n))
    current=start;direction=1 if days>=0 else -1;remaining=abs(days)
    while remaining:
        current+=direction
        if current<61 or current>2958465:return NUM_ERR
        weekday=(datetime.date(1899,12,30)+datetime.timedelta(days=current)).weekday()
        if weekday<5 and current not in holidays:remaining-=1
    return float(current)


def _modern_date_serial(arg, ctx, label):
    if getattr(ctx.workbook,'date_system_1904',False):
        ctx.unsupported.append(label+':1904-date-system')
        return NAME_ERR
    v=ctx.scalar(arg)
    if is_error(v):return v
    if not isinstance(v,(int,float)) or isinstance(v,bool):
        ctx.unsupported.append(label+':non-numeric-date')
        return NAME_ERR
    if not math.isfinite(v) or v<0 or v>=2958466:return NUM_ERR
    v=math.trunc(v)
    if v<61:
        ctx.unsupported.append(label+':early-1900-serial')
        return NAME_ERR
    return v


def FN_DATEDIF(args, ctx):
    if len(args)!=3:return VALUE_ERR
    s=_modern_date_serial(args[0],ctx,'datedif')
    e=_modern_date_serial(args[1],ctx,'datedif')
    unit=to_text(ctx.scalar(args[2]))
    for v in (s,e,unit):
        if is_error(v):return v
    if e<s:return NUM_ERR
    u=unit.upper()
    if u in ('MD','YD','YM'):
        ctx.unsupported.append('datedif:uncertified-unit:'+u)
        return NAME_ERR
    if u not in ('D','M','Y'):return VALUE_ERR
    if u=='D':return float(e-s)
    base=datetime.date(1899,12,30)
    d1=base+datetime.timedelta(days=s);d2=base+datetime.timedelta(days=e)
    if u=='Y':return float(d2.year-d1.year-((d2.month,d2.day)<(d1.month,d1.day)))
    months=(d2.year-d1.year)*12+d2.month-d1.month-(d2.day<d1.day)
    return float(months)


def FN_DATE(args, ctx):
    if len(args)!=3:return VALUE_ERR
    if getattr(ctx.workbook,'date_system_1904',False):
        ctx.unsupported.append('date:1904-date-system')
        return NAME_ERR
    values=[to_number(ctx.scalar(a)) for a in args]
    for v in values:
        if is_error(v):return v
        if not math.isfinite(v):return NUM_ERR
    y,m,d=map(math.trunc,values)
    if not 0<=y<=9999:return NUM_ERR
    if y<1900:y+=1900
    year=y+(m-1)//12;month=(m-1)%12+1
    try:
        result=datetime.date(year,month,1)+datetime.timedelta(days=d-1)
    except (ValueError,OverflowError):return NUM_ERR
    if result<datetime.date(1900,3,1):
        ctx.unsupported.append('date:early-1900-result')
        return NAME_ERR
    return float((result-datetime.date(1899,12,30)).days)


def _datepart(args,ctx,part):
    if len(args)!=1:return VALUE_ERR
    n=_modern_date_serial(args[0],ctx,part)
    if is_error(n):return n
    d=datetime.date(1899,12,30)+datetime.timedelta(days=n)
    return float(getattr(d,part))


def FN_YEAR(args, ctx):return _datepart(args,ctx,'year')
def FN_MONTH(args, ctx):return _datepart(args,ctx,'month')
def FN_DAY(args, ctx):return _datepart(args,ctx,'day')


# ---- array/dynamic (rare in corpus) ----

def FN_UNIQUE(args, ctx):
    """No spill contract exists yet; never silently scalarize a unique list.

    The former flatten/deduplicate routine ignored optional arguments and
    row/column semantics, then Workbook collapsed its Range to one value.
    Registration is retained only to give an explicit diagnostic.
    """
    ctx.unsupported.append('unique:dynamic-array-spill-contract')
    return NAME_ERR


def FN_FORMULATEXT(args, ctx):
    ref = args[0]
    return ctx.formula_text_of(ref)


def FN_GETPIVOTDATA(args, ctx):
    """Scoped saved-display grand total lookup, never target-cache substitution."""
    from .parser import CellRef,RangeRef
    if len(args)<2:return VALUE_ERR
    if len(args)>2:
        ctx.unsupported.append("getpivotdata:item-pairs")
        return NAME_ERR
    data_field=ctx.scalar(args[0])
    if is_error(data_field):return data_field
    ref=args[1]
    if not isinstance(ref,(CellRef,RangeRef)) or ref.ext is not None:
        return REF_ERR
    sheet=ref.sheet or ctx.current_sheet
    if isinstance(ref,CellRef):r1=r2=ref.row;c1=c2=ref.col
    else:r1,r2,c1,c2=ref.r1,ref.r2,ref.c1,ref.c2
    if None in (r1,r2,c1,c2):return REF_ERR
    matches=[]
    for p in ctx.workbook.pivot_snapshots:
        pr1,pc1,pr2,pc2=p['bounds']
        if p['sheet'].lower()==sheet.lower() and r1<=pr2 and r2>=pr1 and c1<=pc2 and c2>=pc1:
            matches.append(p)
    if not matches:return REF_ERR
    if len(matches)!=1:
        ctx.unsupported.append("getpivotdata:multiple-pivots")
        return NAME_ERR
    p=matches[0]
    if p['unsupported_reason']:
        ctx.unsupported.append("getpivotdata:"+p['unsupported_reason'])
        return NAME_ERR
    cell=p['fields'].get(to_text(data_field).casefold())
    if cell is None:return REF_ERR
    ctx.unsupported.append("pivot-snapshot:"+p['name']+":not-refreshed")
    return ctx.cell_value(p['sheet'],*cell)


def FN_XLOOKUP(args, ctx):
    """Certified subset: exact literal, forward, one-dimensional references.

    Do not silently reuse MATCH wildcards or ignore optional mode arguments.
    Return only the selected cell so excluded formulas cannot create cycles.
    """
    from .parser import CellRef, RangeRef, TableRef, Empty
    if not 3 <= len(args) <= 6:return VALUE_ERR
    for pos,default,label in [(4,0,'match-mode'),(5,1,'search-mode')]:
        if len(args)>pos and not isinstance(args[pos],Empty):
            v=ctx.scalar(args[pos])
            if is_error(v):return v
            n=to_number(v)
            if is_error(n):return n
            if n!=default:
                ctx.unsupported.append('xlookup:'+label)
                return NAME_ERR
    lookup=ctx.scalar(args[0])
    if is_error(lookup):return lookup
    if is_blank(lookup):
        ctx.unsupported.append('xlookup:blank-lookup')
        return NAME_ERR
    def ref(a):
        a=ctx.resolve_table(a,return_reference=True) if isinstance(a,TableRef) else a
        return RangeRef(a.sheet,a.ext,a.row,a.col,a.row,a.col) if isinstance(a,CellRef) else a
    la,ra=ref(args[1]),ref(args[2])
    if not isinstance(la,RangeRef) or not isinstance(ra,RangeRef):
        ctx.unsupported.append('xlookup:computed-reference')
        return NAME_ERR
    ls,rs=ctx.reference_shape(la),ctx.reference_shape(ra)
    if ls!=rs:return VALUE_ERR
    if min(ls)!=1:
        ctx.unsupported.append('xlookup:multidimensional-result')
        return NAME_ERR
    values=ctx.resolve_arg(la)
    if is_error(values):return values
    if not isinstance(values,Range) or (values.nrows,values.ncols)!=ls:
        ctx.unsupported.append('xlookup:unmaterialized-blank-tail')
        return NAME_ERR
    vals=list(values.iter_values())
    if any(is_blank(v) or is_error(v) for v in vals):
        ctx.unsupported.append('xlookup:blank-or-error-lookup-array')
        return NAME_ERR
    for i,v in enumerate(vals,1):
        # Unlike MATCH(type=0), XLOOKUP(match_mode=0) treats *?~ literally.
        c=compare(v,lookup)
        if not is_error(c) and c==0:
            handled,value=ctx.index_reference(ra,i,1,2)
            assert handled
            return value
    if len(args)>3 and not isinstance(args[3],Empty):return ctx.scalar(args[3])
    return NA


def FN_N(args, ctx):
    """Numeric identity; TRUE=1,FALSE/text/blank=0; preserve errors/arrays."""
    def conv(v):
        if is_error(v):return v
        if isinstance(v,bool):return 1.0 if v else 0.0
        if isinstance(v,(int,float)):return v
        return 0.0
    v = ctx.resolve_arg(args[0],array=True)
    if isinstance(v,Range):
        return Range(tuple(tuple(conv(x) for x in row) for row in v.cells),sheet=v.sheet,row0=v.row0,col0=v.col0)
    return conv(v)


FUNCTIONS = {
    "N": FN_N,
    "IF": FN_IF, "IFS": FN_IFS, "IFERROR": FN_IFERROR, "IFNA": FN_IFNA,
    "AND": FN_AND, "OR": FN_OR, "NOT": FN_NOT,
    "SUM": FN_SUM, "COUNT": FN_COUNT, "COUNTA": FN_COUNTA, "COUNTBLANK": FN_COUNTBLANK,
    "AVERAGE": FN_AVERAGE, "MAX": FN_MAX, "MIN": FN_MIN,
    "ABS": FN_ABS, "INT": FN_INT, "ROUND": FN_ROUND, "ROUNDUP": FN_ROUNDUP,
    "ROUNDDOWN": FN_ROUNDDOWN, "SQRT": FN_SQRT, "POWER": FN_POWER,
    "UPPER": FN_UPPER, "LOWER": FN_LOWER, "TRIM": FN_TRIM, "LEN": FN_LEN,
    "LEFT": FN_LEFT, "RIGHT": FN_RIGHT, "MID": FN_MID, "FIND": FN_FIND,
    "SEARCH": FN_SEARCH, "SUBSTITUTE": FN_SUBSTITUTE, "CONCATENATE": FN_CONCATENATE,
    "EXACT": FN_EXACT, "VALUE": FN_VALUE, "NUMBERVALUE": FN_NUMBERVALUE, "TEXT": FN_TEXT,
    "ISERROR": FN_ISERROR, "ISNA": FN_ISNA, "ISBLANK": FN_ISBLANK,
    "ISNUMBER": FN_ISNUMBER, "ISTEXT": FN_ISTEXT, "ISLOGICAL": FN_ISLOGICAL,
    "NA": FN_NA, "ROW": FN_ROW, "COLUMN": FN_COLUMN,
    "INDEX": FN_INDEX, "MATCH": FN_MATCH, "VLOOKUP": FN_VLOOKUP,
    "HLOOKUP": FN_HLOOKUP, "LOOKUP": FN_LOOKUP, "XLOOKUP": FN_XLOOKUP,
    "SUMIF": FN_SUMIF, "SUMIFS": FN_SUMIFS, "COUNTIF": FN_COUNTIF,
    "COUNTIFS": FN_COUNTIFS, "AVERAGEIFS": FN_AVERAGEIFS,
    "SUMPRODUCT": FN_SUMPRODUCT, "SUBTOTAL": FN_SUBTOTAL,
    "TODAY": FN_TODAY, "NOW": FN_NOW, "WORKDAY": FN_WORKDAY, "DATEDIF": FN_DATEDIF, "DATE": FN_DATE,
    "YEAR": FN_YEAR, "MONTH": FN_MONTH, "DAY": FN_DAY,
    "UNIQUE": FN_UNIQUE, "FORMULATEXT": FN_FORMULATEXT, "GETPIVOTDATA": FN_GETPIVOTDATA,
}
