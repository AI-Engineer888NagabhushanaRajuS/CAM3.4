"""Excel value model: scalar types, error values, coercion rules.

Semantics follow Excel's observable behaviour as exercised by the CAM corpus:
- Cells hold: empty (Blank), float, str, bool, or ErrorValue.
- Errors propagate through arithmetic/comparison but are catchable by
  IFERROR / ISERROR / ISNA / ERROR.TYPE.
- Text<->number coercion happens in arithmetic context, never in comparisons
  (in comparisons, text > number > FALSE > TRUE ordering applies per type).
Sources: behaviour required by corpus formulas (documented in FE-3 design doc);
where Excel semantics are ambiguous the rule is stated inline.
"""
from __future__ import annotations


class ErrorValue:
    """An Excel error literal, e.g. #N/A, #VALUE!, #REF!, #DIV/0!, #NAME?, #NUM!, #NULL!"""
    __slots__ = ("code",)

    def __init__(self, code: str):
        self.code = code

    def __repr__(self):
        return self.code

    def __eq__(self, other):
        return isinstance(other, ErrorValue) and other.code == self.code

    def __hash__(self):
        return hash(self.code)


NA = ErrorValue("#N/A")
VALUE_ERR = ErrorValue("#VALUE!")
REF_ERR = ErrorValue("#REF!")
DIV0 = ErrorValue("#DIV/0!")
NAME_ERR = ErrorValue("#NAME?")
NUM_ERR = ErrorValue("#NUM!")
NULL_ERR = ErrorValue("#NULL!")


class Blank:
    """The empty cell value. Distinct from "" (empty text)."""
    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self):
        return "<blank>"

    def __eq__(self, other):
        return isinstance(other, Blank)

    def __hash__(self):
        return hash("<blank>")


BLANK = Blank()


class Range:
    """A rectangular block of cells passed to a function.

    cells: tuple of tuples of values (row-major).
    anchors: (sheet, first_row, first_col) 1-based of the top-left cell, used by
             ROW()/INDEX() that need absolute positions. May be None.
    """
    __slots__ = ("cells", "sheet", "row0", "col0")

    def __init__(self, cells, sheet=None, row0=None, col0=None):
        self.cells = cells
        self.sheet = sheet
        self.row0 = row0
        self.col0 = col0

    @property
    def nrows(self):
        return len(self.cells)

    @property
    def ncols(self):
        return len(self.cells[0]) if self.cells else 0

    def iter_values(self):
        for row in self.cells:
            for v in row:
                yield v


def is_error(v):
    return isinstance(v, ErrorValue)


def is_blank(v):
    return isinstance(v, Blank)


# ---------------- coercion ----------------

TRUE_TEXTS = {"TRUE"}
FALSE_TEXTS = {"FALSE"}


def to_number(v, err=VALUE_ERR):
    """Excel arithmetic-context coercion.

    blank->0, bool->1/0, number->number, text parsed strictly ("1,234" is text
    that fails -> #VALUE!; leading/trailing spaces tolerated; ""->0 in direct
    ref context but here "" -> #VALUE! per Excel arithmetic on text "").
    """
    if is_error(v):
        return v
    if is_blank(v):
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            # Excel: ="", used in arithmetic via cell ref gives #VALUE!
            return err
        # Excel accepts %, $, and scientific notation in implicit conversion
        try:
            return float(s)
        except ValueError:
            pass
        try:
            if s.endswith("%"):
                return float(s[:-1]) / 100.0
        except ValueError:
            pass
        return err
    return err


def to_text(v):
    """Concatenation-context coercion."""
    if is_error(v):
        return v
    if is_blank(v):
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return repr(v)
    if isinstance(v, int):
        return str(v)
    return v


def to_bool(v):
    """Condition context (IF argument). Numbers: 0 is FALSE. Text must be
    TRUE/FALSE (case-insensitive) else #VALUE!."""
    if is_error(v):
        return v
    if is_blank(v):
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        u = v.strip().upper()
        if u in TRUE_TEXTS:
            return True
        if u in FALSE_TEXTS:
            return False
        return VALUE_ERR
    return VALUE_ERR


# ---------------- comparison ----------------

def _type_rank(v):
    # Excel sort order for mixed-type comparison: number < text < FALSE < TRUE
    if is_blank(v):
        return 0  # blank compares equal to 0 and "" contextually; handled by caller
    if isinstance(v, bool):
        return 3 if v else 2
    if isinstance(v, (int, float)):
        return 0
    return 1


def compare(a, b):
    """Excel 3-way comparison used by =, <>, <, <=, >, >=.
    Returns -1/0/1, or an ErrorValue.
    Blanks are equal to 0 and to "" (Excel: blank = 0 is TRUE, blank = "" is TRUE).
    Text comparison is case-insensitive.
    """
    if is_error(a):
        return a
    if is_error(b):
        return b
    if is_blank(a) and is_blank(b):
        return 0
    if is_blank(a):
        if isinstance(b, bool):
            a = False
        elif isinstance(b, (int, float)):
            a = 0.0
        elif isinstance(b, str):
            a = ""
    elif is_blank(b):
        if isinstance(a, bool):
            b = False
        elif isinstance(a, (int, float)):
            b = 0.0
        elif isinstance(a, str):
            b = ""
    ra, rb = _type_rank(a), _type_rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    if isinstance(a, str):
        la, lb = a.lower(), b.lower()
        return (la > lb) - (la < lb)
    if isinstance(a, float) or isinstance(b, float):
        if not (isinstance(a, bool) or isinstance(b, bool)):
            # Excel compares numbers at 15 significant decimal digits
            fa, fb = float(a), float(b)
            if fa != fb and float(f"{fa:.15g}") == float(f"{fb:.15g}"):
                return 0
    return (a > b) - (a < b)
