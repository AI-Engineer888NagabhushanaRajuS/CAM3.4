"""Lexer + recursive-descent parser for Excel A1-style formulas.

Grammar coverage (driven by the CAM corpus, not a claim of full Excel parity):
  literals: numbers, "double quoted strings" ("" escape), TRUE/FALSE, #N/A etc.
  refs: A1, $A$1, A1:B2, A:A, $A:$A, 1:3, 'Sheet Name'!A1, Sheet1!A1,
        [1]Sheet!A1 (external workbook), [1]'Sheet'!A1,
        structured table refs: Table[Col], Table[[#This Row],[Col]],
        Table[[#Totals],[Col]], Table[[#Headers],[Col]], Table[#Data], Table[#All]
  operators (prec high->low): % postfix, ^ , * / , + - , & , = <> < <= > >=
  unary +/- ; parentheses; function calls; comma arg separator.
  intersection (space) and union (,) of ranges are NOT in the corpus -> unsupported
  (parse error), stated explicitly in the design doc.
"""
from __future__ import annotations

from .values import ErrorValue, NA, VALUE_ERR, REF_ERR, DIV0, NAME_ERR, NUM_ERR, NULL_ERR

ERRORS = {
    "#N/A": NA, "#VALUE!": VALUE_ERR, "#REF!": REF_ERR, "#DIV/0!": DIV0,
    "#NAME?": NAME_ERR, "#NUM!": NUM_ERR, "#NULL!": NULL_ERR,
}


# ---------------- lexer ----------------

T_NUM, T_STR, T_BOOL, T_ERR, T_REF, T_FUNC, T_OP, T_LP, T_RP, T_COMMA, T_EOF, T_SREF = range(12)


class Token:
    __slots__ = ("kind", "value")

    def __init__(self, kind, value):
        self.kind = kind
        self.value = value

    def __repr__(self):
        return f"Token({self.kind},{self.value!r})"


class ParseError(Exception):
    pass


def _is_name_char(c):
    return c.isalnum() or c in "._"


def lex(text: str):
    """Tokenize the formula body (leading '=' already stripped)."""
    toks = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == '"':
            j = i + 1
            buf = []
            while j < n:
                if text[j] == '"':
                    if j + 1 < n and text[j + 1] == '"':
                        buf.append('"')
                        j += 2
                        continue
                    break
                buf.append(text[j])
                j += 1
            if j >= n:
                raise ParseError("unterminated string")
            toks.append(Token(T_STR, "".join(buf)))
            i = j + 1
            continue
        if c == "'":
            # quoted sheet name: 'Sheet Name'!  or '[1]Sheet'!
            j = i + 1
            buf = []
            while j < n:
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        buf.append("'")
                        j += 2
                        continue
                    break
                buf.append(text[j])
                j += 1
            if j >= n or j + 1 >= n or text[j + 1] != "!":
                raise ParseError("bad quoted sheet ref")
            sheet_name = "".join(buf)
            import re
            extmatch = re.match(r"^\[(\d+)\](.+)$", sheet_name)
            if extmatch:
                toks.append(Token(T_REF, ("ext", extmatch.group(1), extmatch.group(2))))
            else:
                toks.append(Token(T_REF, ("sheet", sheet_name)))
            i = j + 2
            continue
        if c == "[":
            j = text.find("]", i)
            if j < 0:
                raise ParseError("bad external ref")
            if not text[i + 1:j].isdigit():
                # structured table reference: consume balanced brackets
                # (' escapes the next char inside column names, e.g. Qty '#N)
                depth = 1
                k = i + 1
                buf = []
                while k < n and depth:
                    ch = text[k]
                    if ch == "'" and k + 1 < n:
                        buf.append(ch); buf.append(text[k + 1]); k += 2
                        continue
                    if ch == "[":
                        depth += 1
                    elif ch == "]":
                        depth -= 1
                        if depth == 0:
                            k += 1
                            break
                    buf.append(ch)
                    k += 1
                if depth:
                    raise ParseError("unbalanced structured ref")
                toks.append(Token(T_SREF, "".join(buf)))
                i = k
                continue
            book = text[i + 1:j]
            # after ] comes a sheet name (unquoted) then !
            k = j + 1
            m = k
            while m < n and text[m] != "!":
                m += 1
            if m >= n:
                raise ParseError("bad external ref")
            toks.append(Token(T_REF, ("ext", book, text[k:m])))
            i = m + 1
            continue
        if c == "#":
            for code, ev in ERRORS.items():
                if text.startswith(code, i):
                    toks.append(Token(T_ERR, ev))
                    i += len(code)
                    break
            else:
                raise ParseError(f"bad error literal at {i}")
            continue
        if c.isdigit() or (c == "." and i + 1 < n and text[i + 1].isdigit()):
            j = i
            while j < n and (text[j].isdigit() or text[j] == "."):
                j += 1
            if j < n and text[j] in "Ee" and j + 1 < n and (text[j + 1].isdigit() or (text[j + 1] in "+-" and j + 2 < n and text[j + 2].isdigit())):
                j += 1
                if text[j] in "+-":
                    j += 1
                while j < n and text[j].isdigit():
                    j += 1
            toks.append(Token(T_NUM, float(text[i:j])))
            i = j
            continue
        if c.isalpha() or c == "_" or c == "$":
            # read a ref/name token: optional $COL$ROW pieces, sheet prefix, func
            j = i
            while j < n and (_is_name_char(text[j]) or text[j] == "$"):
                j += 1
            word = text[i:j]
            # sheet-qualified unquoted ref: Name!...
            if j < n and text[j] == "!" and not word.startswith("$"):
                toks.append(Token(T_REF, ("sheet", word)))
                i = j + 1
                continue
            # function call
            if j < n and text[j] == "(":
                toks.append(Token(T_FUNC, word.upper()))
                i = j  # leave '(' for main loop
                continue
            # boolean literal
            if word.upper() == "TRUE":
                toks.append(Token(T_BOOL, True))
                i = j
                continue
            if word.upper() == "FALSE":
                toks.append(Token(T_BOOL, False))
                i = j
                continue
            toks.append(Token(T_REF, ("a1", word)))
            i = j
            continue
        if c == "(":
            toks.append(Token(T_LP, c))
            i += 1
            continue
        if c == ")":
            toks.append(Token(T_RP, c))
            i += 1
            continue
        if c == ",":
            toks.append(Token(T_COMMA, c))
            i += 1
            continue
        if c in "+-*/^&%":
            toks.append(Token(T_OP, c))
            i += 1
            continue
        if c in "=<>":
            if i + 1 < n and text[i + 1] == "=":
                toks.append(Token(T_OP, c + "="))
                i += 2
            elif c == "<" and i + 1 < n and text[i + 1] == ">":
                toks.append(Token(T_OP, "<>"))
                i += 2
            else:
                toks.append(Token(T_OP, c))
                i += 1
            continue
        if c == ":":
            toks.append(Token(T_OP, ":"))
            i += 1
            continue
        raise ParseError(f"unexpected char {c!r} at {i}")
    toks.append(Token(T_EOF, None))
    return toks


# ---------------- AST ----------------

class Node:
    __slots__ = ()


class Num(Node):
    __slots__ = ("v",)

    def __init__(self, v):
        self.v = v


class Str(Node):
    __slots__ = ("v",)

    def __init__(self, v):
        self.v = v


class Bool(Node):
    __slots__ = ("v",)

    def __init__(self, v):
        self.v = v


class Err(Node):
    __slots__ = ("v",)

    def __init__(self, v):
        self.v = v


class CellRef(Node):
    """sheet: None (current), or name string; ext: workbook index or None.
    row/col 1-based; abs flags kept for fidelity."""
    __slots__ = ("sheet", "ext", "row", "col", "row_abs", "col_abs")

    def __init__(self, sheet, ext, row, col, row_abs=False, col_abs=False):
        self.sheet, self.ext, self.row, self.col = sheet, ext, row, col
        self.row_abs, self.col_abs = row_abs, col_abs


class RangeRef(Node):
    """rectangular range. Rows/cols may be None for whole-col/whole-row refs."""
    __slots__ = ("sheet", "ext", "r1", "c1", "r2", "c2", "whole_cols", "whole_rows")

    def __init__(self, sheet, ext, r1, c1, r2, c2, whole_cols=False, whole_rows=False):
        self.sheet, self.ext = sheet, ext
        self.r1, self.c1, self.r2, self.c2 = r1, c1, r2, c2
        self.whole_cols, self.whole_rows = whole_cols, whole_rows


class FuncCall(Node):
    __slots__ = ("name", "args")

    def __init__(self, name, args):
        self.name, self.args = name, args


class BinOp(Node):
    __slots__ = ("op", "l", "r")

    def __init__(self, op, l, r):
        self.op, self.l, self.r = op, l, r


class UnOp(Node):
    __slots__ = ("op", "x")

    def __init__(self, op, x):
        self.op, self.x = op, x


class Percent(Node):
    __slots__ = ("x",)

    def __init__(self, x):
        self.x = x


class DynRange(Node):
    """Runtime-bounded range: INDEX(col,rowexpr):INDEX(col,rowexpr).
    The corpus's bounded-range pattern (SUMIFS over INDEX(...):INDEX(...))."""
    __slots__ = ("l", "r")

    def __init__(self, l, r):
        self.l, self.r = l, r


class Empty(Node):
    """Explicit empty argument, distinct from absent: VLOOKUP(a,b,c,)."""
    __slots__ = ()


class NameRef(Node):
    """A bare name that is not a cell ref (defined name). Resolved via workbook."""
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


def _sref_items(inner):
    """Split structured-ref spec into items.
    '[#This Row],[Part Number]' -> ['#This Row', 'Part Number']; 'Assembly' -> ['Assembly'].
    ' unescapes the next char."""
    inner = inner.strip()
    if not inner.startswith("["):
        return [_unescape_sref(inner)]
    items = []
    i, n = 0, len(inner)
    while i < n:
        if inner[i] == "[":
            depth = 1
            j = i + 1
            buf = []
            while j < n and depth:
                ch = inner[j]
                if ch == "'" and j + 1 < n:
                    buf.append(inner[j + 1]); j += 2
                    continue
                if ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                buf.append(ch)
                j += 1
            items.append("".join(buf))
            while j < n and inner[j] in ", ":
                j += 1
            i = j
        else:
            i += 1
    return items


def _unescape_sref(s):
    out = []
    i = 0
    while i < len(s):
        if s[i] == "'" and i + 1 < len(s):
            out.append(s[i + 1]); i += 2
        else:
            out.append(s[i]); i += 1
    return "".join(out)


class TableRef(Node):
    """Structured table reference. table=None for bare [@Col] form.
    spec: raw inner text; items() -> list of selectors/column names."""
    __slots__ = ("table", "spec")

    def __init__(self, table, spec):
        self.table, self.spec = table, spec

    def items(self):
        return _sref_items(self.spec)

    def selectors(self):
        """(row_selector_keyword_or_None, column_name_or_None)."""
        row_sel, col = None, None
        for it in self.items():
            if it.startswith("#"):
                row_sel = it.lstrip("#").replace(" ", "").lower()
            else:
                col = it
        return row_sel, col


# ---------------- parser ----------------

_A1 = __import__("re").compile(r"^\$?([A-Za-z]{1,3})\$?([0-9]+)$")
_COL = __import__("re").compile(r"^\$?([A-Za-z]{1,3})$")
_ROW = __import__("re").compile(r"^\$?([0-9]+)$")


def col_to_num(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def _split_a1(word):
    """Return (col, row, col_abs, row_abs) for A1-style word or None."""
    m = _A1.match(word)
    if m:
        colpart = word.split("$")[0] if "$" not in word else None
        col_abs = word.startswith("$")
        mid = word.lstrip("$")
        if "$" in mid:
            row_abs = True
            letters = mid.split("$")[0]
        else:
            row_abs = False
            letters = mid.rstrip("0123456789")
        return col_to_num(m.group(1)), int(m.group(2)), col_abs, row_abs
    return None


def _canonical_static_range(ref):
 if not isinstance(ref,RangeRef):return ref
 if ref.whole_cols:
  if 1<=ref.c1<=16384 and 1<=ref.c2<=16384:ref.c1,ref.c2=sorted((ref.c1,ref.c2))
 elif ref.whole_rows:
  if 1<=ref.r1<=1048576 and 1<=ref.r2<=1048576:ref.r1,ref.r2=sorted((ref.r1,ref.r2))
 elif all([1<=ref.r1<=1048576,1<=ref.r2<=1048576,1<=ref.c1<=16384,1<=ref.c2<=16384]):
  ref.r1,ref.r2=sorted((ref.r1,ref.r2));ref.c1,ref.c2=sorted((ref.c1,ref.c2))
 return ref


class Parser:
    def __init__(self, toks):
        self.toks = toks
        self.pos = 0

    def peek(self):
        return self.toks[self.pos]

    def next(self):
        t = self.toks[self.pos]
        self.pos += 1
        return t

    def expect(self, kind, val=None):
        t = self.next()
        if t.kind != kind or (val is not None and t.value != val):
            raise ParseError(f"expected {kind} {val}, got {t}")
        return t

    def parse(self):
        node = self.parse_cmp()
        if self.peek().kind != T_EOF:
            raise ParseError(f"trailing tokens: {self.peek()}")
        return node

    def parse_cmp(self):
        node = self.parse_concat()
        while self.peek().kind == T_OP and self.peek().value in ("=", "<>", "<", "<=", ">", ">="):
            op = self.next().value
            node = BinOp(op, node, self.parse_concat())
        return node

    def parse_concat(self):
        node = self.parse_add()
        while self.peek().kind == T_OP and self.peek().value == "&":
            self.next()
            node = BinOp("&", node, self.parse_add())
        return node

    def parse_add(self):
        node = self.parse_mul()
        while self.peek().kind == T_OP and self.peek().value in ("+", "-"):
            op = self.next().value
            node = BinOp(op, node, self.parse_mul())
        return node

    def parse_mul(self):
        node = self.parse_pow()
        while self.peek().kind == T_OP and self.peek().value in ("*", "/"):
            op = self.next().value
            node = BinOp(op, node, self.parse_pow())
        return node

    def parse_pow(self):
        node = self.parse_unary()
        while self.peek().kind == T_OP and self.peek().value == "^":
            self.next()
            node = BinOp("^", node, self.parse_unary())
        return node

    def parse_unary(self):
        if self.peek().kind == T_OP and self.peek().value == "-":
            self.next()
            return UnOp("-", self.parse_unary())
        if self.peek().kind == T_OP and self.peek().value == "+":
            self.next()
            return self.parse_unary()
        return self.parse_postfix()

    def parse_postfix(self):
        node = self.parse_atom()
        while self.peek().kind == T_OP and self.peek().value == "%":
            self.next()
            node = Percent(node)
        # dynamic range: atom ':' atom (e.g. INDEX(col,r1):INDEX(col,r2))
        if isinstance(node, (FuncCall, CellRef)) and self.peek().kind == T_OP and self.peek().value == ":":
            self.next()
            rhs = self.parse_atom()
            while self.peek().kind == T_OP and self.peek().value == "%":
                self.next()
                rhs = Percent(rhs)
            node = DynRange(node, rhs)
        return node

    def parse_atom(self):
        t = self.next()
        if t.kind == T_NUM:
            return Num(t.value)
        if t.kind == T_STR:
            return Str(t.value)
        if t.kind == T_BOOL:
            return Bool(t.value)
        if t.kind == T_ERR:
            return Err(t.value)
        if t.kind == T_LP:
            node = self.parse_cmp()
            self.expect(T_RP)
            return node
        if t.kind == T_FUNC:
            self.expect(T_LP)
            args = []
            if self.peek().kind != T_RP:
                args.append(Empty() if self.peek().kind in (T_COMMA, T_RP) else self.parse_cmp())
                while self.peek().kind == T_COMMA:
                    self.next()
                    args.append(Empty() if self.peek().kind in (T_COMMA, T_RP) else self.parse_cmp())
            self.expect(T_RP)
            return FuncCall(t.value, args)
        if t.kind == T_SREF:
            return TableRef(None, t.value)
        if t.kind == T_REF:
            if t.value[0] == "a1" and self.peek().kind == T_SREF:
                return TableRef(t.value[1], self.next().value)
            sheet, ext, word = self._ref_triple(t)
            if word is None:
                return Err(REF_ERR)  # sheet-qualified baked #REF!
            # A cell:INDEX(...) endpoint is bound by parse_postfix and the
            # shared dynamic-reference resolver, not a static A1 range end.
            if (self.peek().kind == T_OP and self.peek().value == ":"
                    and self.toks[self.pos + 1].kind == T_FUNC
                    and self.toks[self.pos + 1].value.removeprefix("_XLFN.") == "INDEX"
                    and _split_a1(word)):
                return self._a1_node(word, sheet=sheet, ext=ext)
            # range?
            if self.peek().kind == T_OP and self.peek().value == ":":
                self.next()
                t2 = self.next()
                if t2.kind != T_REF:
                    raise ParseError("bad range end")
                sheet2, ext2, word2 = self._ref_triple(t2)
                if sheet is not None and sheet2 is not None and (sheet.lower() != sheet2.lower() or ext != ext2):
                    raise ParseError("unsupported-reference:mixed-explicit-sheet-or-book-range")
                return self._range_from_words(sheet or sheet2, ext or ext2, word, word2)
            return self._a1_node(word, sheet=sheet, ext=ext)
        raise ParseError(f"unexpected token {t}")

    def _ref_triple(self, t):
        """Consume a ref token (plus the a1 token for prefixed forms).
        Returns (sheet, ext, a1word)."""
        kind = t.value[0]
        if kind == "a1":
            return (None, None, t.value[1])
        if kind == "sheet":
            t2 = self.next()
            if t2.kind == T_ERR:
                return (t.value[1], None, None)  # 'Sheet'!#REF! baked broken ref
            if t2.kind != T_REF or t2.value[0] != "a1":
                raise ParseError("sheet prefix without cell")
            return (t.value[1], None, t2.value[1])
        if kind == "ext":
            t2 = self.next()
            if t2.kind != T_REF or t2.value[0] != "a1":
                raise ParseError("external ref without cell")
            return (t.value[2], t.value[1], t2.value[1])
        raise ParseError("bad ref token")

    def _range_from_words(self, sheet, ext, w1, w2):
        a = _split_a1(w1)
        b = _split_a1(w2)
        if a and b:
            return _canonical_static_range(RangeRef(sheet, ext, a[1], a[0], b[1], b[0]))
        c1 = _COL.match(w1)
        c2 = _COL.match(w2)
        if c1 and c2:
            return _canonical_static_range(RangeRef(sheet, ext, None, col_to_num(c1.group(1)), None, col_to_num(c2.group(1)), whole_cols=True))
        r1 = _ROW.match(w1)
        r2 = _ROW.match(w2)
        if r1 and r2:
            return _canonical_static_range(RangeRef(sheet, ext, int(r1.group(1)), None, int(r2.group(1)), None, whole_rows=True))
        raise ParseError(f"unsupported range {w1}:{w2}")

    def _a1_node(self, word, sheet=None, ext=None):
        m = _split_a1(word)
        if m:
            col, row, col_abs, row_abs = m
            return CellRef(sheet, ext, row, col, row_abs, col_abs)
        if _COL.match(word):
            return RangeRef(sheet, ext, None, col_to_num(word.lstrip("$")), None, col_to_num(word.lstrip("$")), whole_cols=True)
        if _ROW.match(word):
            rn = int(word.lstrip("$"))
            return RangeRef(sheet, ext, rn, None, rn, None, whole_rows=True)
        return NameRef(word)


def parse_formula(text: str) -> Node:
    body = text.strip()
    if body.startswith("="):
        body = body[1:]
    return Parser(lex(body)).parse()
