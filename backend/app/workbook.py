"""Read an .xlsx financial database with the standard library and evaluate its own cell formulas.

The workbook defines every ratio (KPI sheets are formulas linked to the "<Company> Inputs" sheets).
When the file carries saved results (it was last saved by Excel), those are used. When it does not
(files written by tools often store formulas without results), the backend evaluates the workbook's
own formula text, exactly as written. The backend never defines a ratio itself.

Supported formula grammar: numbers, strings, cell and range references (optionally sheet-qualified),
+ - * / ^ &, comparisons, parentheses, and the functions SUM, IF, IFERROR, COUNT, OR, AND, ABS, MIN, MAX.

Blank cells: the workbook notes say blank inputs are "not verified, not zero". So a blank referenced in
arithmetic or inside SUM makes the result "not available" instead of being treated as 0. In comparisons
a blank compares as 0, as in Excel (so IF(x=0,"n/m",...) still works).
"""
from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"


class WorkbookError(Exception):
    pass


class XlErr:
    """An Excel error value such as #DIV/0!."""

    def __init__(self, code: str):
        self.code = code

    def __repr__(self) -> str:
        return self.code


BLANK = None


def col_to_num(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def num_to_col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def split_ref(ref: str) -> tuple[str, int]:
    m = re.fullmatch(r"\$?([A-Z]+)\$?(\d+)", ref)
    if not m:
        raise WorkbookError(f"Bad cell reference {ref}")
    return m.group(1), int(m.group(2))


def excel_date(serial: float) -> date:
    return date(1899, 12, 30) + timedelta(days=int(serial))


# --------------------------------------------------------------------------- reading
class Workbook:
    def __init__(self, path: Path):
        self.path = Path(path)
        try:
            z = zipfile.ZipFile(self.path)
        except (zipfile.BadZipFile, OSError) as exc:
            raise WorkbookError(f"The file {self.path.name} is not a readable .xlsx workbook.") from exc
        with z:
            names = set(z.namelist())
            strings: list[str] = []
            if "xl/sharedStrings.xml" in names:
                for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(M + "si"):
                    strings.append("".join(t.text or "" for t in si.iter(M + "t")))
            wb = ET.fromstring(z.read("xl/workbook.xml"))
            rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(PR + "Relationship")}
            self.sheet_names: list[str] = []
            self.cells: dict[str, dict[str, tuple]] = {}
            for s in wb.find(M + "sheets"):
                name = s.get("name")
                target = rels[s.get(R + "id")].lstrip("/")
                target = target if target.startswith("xl/") else "xl/" + target
                self.sheet_names.append(name)
                self.cells[name] = self._read_sheet(ET.fromstring(z.read(target)), strings)
        self._memo: dict[tuple[str, str], object] = {}
        self._active: set[tuple[str, str]] = set()
        self.evaluated_formulas = 0

    @staticmethod
    def _read_sheet(root, strings) -> dict[str, tuple]:
        """ref -> (cached value or BLANK, formula text or None)."""
        out = {}
        for c in root.iter(M + "c"):
            ref, t = c.get("r"), c.get("t")
            v, f = c.find(M + "v"), c.find(M + "f")
            formula = f.text if f is not None and f.text else None
            val = BLANK
            if t == "s" and v is not None:
                val = strings[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(M + "t"))
            elif t == "str" and v is not None:
                val = v.text or ""
            elif t == "b" and v is not None:
                val = v.text == "1"
            elif t == "e" and v is not None:
                val = XlErr(v.text)
            elif v is not None and v.text not in (None, ""):
                val = float(v.text)
            if val is BLANK and formula is None:
                continue
            out[ref] = (val, formula)
        return out

    # ---- public --------------------------------------------------------------
    def raw(self, sheet: str, ref: str):
        """Stored value without evaluation (BLANK if empty)."""
        return self.cells.get(sheet, {}).get(ref, (BLANK, None))[0]

    def formula(self, sheet: str, ref: str) -> str | None:
        return self.cells.get(sheet, {}).get(ref, (BLANK, None))[1]

    def value(self, sheet: str, ref: str):
        """Saved result when present, otherwise the evaluated formula, otherwise the stored value."""
        if sheet not in self.cells:
            return XlErr("#REF!")
        key = (sheet, ref)
        if key in self._memo:
            return self._memo[key]
        cached, formula = self.cells[sheet].get(ref, (BLANK, None))
        if formula is None or cached is not BLANK:
            return cached
        if key in self._active:
            return XlErr("#CIRC!")
        self._active.add(key)
        try:
            result = Evaluator(self, sheet).run(formula)
            self.evaluated_formulas += 1
        finally:
            self._active.discard(key)
        self._memo[key] = result
        return result

    def text(self, sheet: str, ref: str) -> str:
        v = self.value(sheet, ref)
        if v is BLANK or isinstance(v, XlErr):
            return ""
        if isinstance(v, float):
            return format(v, "g")
        return str(v)

    def rows(self, sheet: str) -> list[int]:
        return sorted({split_ref(r)[1] for r in self.cells.get(sheet, {})})


# --------------------------------------------------------------------------- formulas
TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<ref>(?:(?:'(?:[^']|'')+'|[A-Za-z_][\w.]*)!)?\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)(?![\w(])
  | (?P<func>[A-Z][A-Z0-9.]*)\(
  | (?P<num>\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)
  | (?P<str>"(?:[^"]|"")*")
  | (?P<bool>TRUE|FALSE)(?![\w(])
  | (?P<op><>|<=|>=|[-+*/^&=<>(),%])
""", re.X)


class Evaluator:
    def __init__(self, wb: Workbook, sheet: str):
        self.wb, self.sheet = wb, sheet
        self.toks: list[tuple[str, str]] = []
        self.i = 0

    def run(self, formula: str):
        text = formula[1:] if formula.startswith("=") else formula
        pos = 0
        while pos < len(text):
            m = TOKEN_RE.match(text, pos)
            if not m:
                return XlErr("#NAME?")
            kind = m.lastgroup
            if kind != "ws":
                self.toks.append((kind, m.group(kind)))
            pos = m.end()
        self.toks.append(("end", ""))
        try:
            v = self.compare()
            if self.peek()[0] != "end":
                return XlErr("#NAME?")
        except WorkbookError:
            return XlErr("#NAME?")
        return v[0] if isinstance(v, list) and len(v) == 1 else (XlErr("#VALUE!") if isinstance(v, list) else v)

    # ---- token helpers -------------------------------------------------------
    def peek(self):
        return self.toks[self.i]

    def take(self, value=None):
        t = self.toks[self.i]
        if value is not None and t[1] != value:
            raise WorkbookError(f"expected {value}")
        self.i += 1
        return t

    # ---- grammar -------------------------------------------------------------
    def compare(self):
        left = self.concat()
        while self.peek()[0] == "op" and self.peek()[1] in ("=", "<>", "<", ">", "<=", ">="):
            op = self.take()[1]
            right = self.concat()
            left = _compare(op, scalar(left), scalar(right))
        return left

    def concat(self):
        left = self.additive()
        while self.peek() == ("op", "&"):
            self.take()
            right = self.additive()
            a, b = scalar(left), scalar(right)
            left = a if isinstance(a, XlErr) else b if isinstance(b, XlErr) else _as_text(a) + _as_text(b)
        return left

    def additive(self):
        left = self.term()
        while self.peek()[0] == "op" and self.peek()[1] in "+-":
            op = self.take()[1]
            left = _arith(op, scalar(left), scalar(self.term()))
        return left

    def term(self):
        left = self.power()
        while self.peek()[0] == "op" and self.peek()[1] in "*/":
            op = self.take()[1]
            left = _arith(op, scalar(left), scalar(self.power()))
        return left

    def power(self):
        left = self.unary()
        while self.peek() == ("op", "^"):
            self.take()
            left = _arith("^", scalar(left), scalar(self.unary()))
        return left

    def unary(self):
        if self.peek() in (("op", "-"), ("op", "+")):
            op = self.take()[1]
            v = scalar(self.unary())
            return _arith("*", -1.0 if op == "-" else 1.0, v)
        v = self.primary()
        if self.peek() == ("op", "%"):
            self.take()
            v = _arith("/", scalar(v), 100.0)
        return v

    def primary(self):
        kind, text = self.take()
        if kind == "num":
            return float(text)
        if kind == "str":
            return text[1:-1].replace('""', '"')
        if kind == "bool":
            return text == "TRUE"
        if kind == "ref":
            return self.ref(text)
        if kind == "op" and text == "(":
            v = self.compare()
            self.take(")")
            return v
        if kind == "func":
            return self.call(text)
        raise WorkbookError(f"unexpected {text}")

    def ref(self, text: str):
        sheet = self.sheet
        if "!" in text:
            s, text = text.rsplit("!", 1)
            sheet = s[1:-1].replace("''", "'") if s.startswith("'") else s
        if ":" in text:
            a, b = text.split(":")
            (c1, r1), (c2, r2) = split_ref(a), split_ref(b)
            out = []
            for row in range(min(r1, r2), max(r1, r2) + 1):
                for col in range(min(col_to_num(c1), col_to_num(c2)), max(col_to_num(c1), col_to_num(c2)) + 1):
                    out.append(self.wb.value(sheet, f"{num_to_col(col)}{row}"))
            return out
        c, r = split_ref(text)
        return self.wb.value(sheet, f"{c}{r}")

    def args(self) -> list:
        """Evaluate every argument (IF/IFERROR branches are evaluated eagerly; formulas have no side effects)."""
        out = []
        if self.peek() == ("op", ")"):
            self.take()
            return out
        while True:
            out.append(self.compare())
            t = self.take()
            if t == ("op", ")"):
                return out
            if t != ("op", ","):
                raise WorkbookError("expected , or )")

    def call(self, name: str):
        a = self.args()
        flat = [x for v in a for x in (v if isinstance(v, list) else [v])]
        if name == "SUM":
            if any(isinstance(x, XlErr) for x in flat):
                return next(x for x in flat if isinstance(x, XlErr))
            if any(x is BLANK for x in flat):
                return BLANK  # a blank input is "not verified", so a total over it is not available
            return float(sum(x for x in flat if isinstance(x, (int, float)) and not isinstance(x, bool)))
        if name == "COUNT":
            return float(sum(1 for x in flat if isinstance(x, float)))
        if name in ("MIN", "MAX"):
            nums = [x for x in flat if isinstance(x, float)]
            if any(isinstance(x, XlErr) for x in flat):
                return next(x for x in flat if isinstance(x, XlErr))
            return (min if name == "MIN" else max)(nums) if nums else 0.0
        if name == "ABS":
            v = scalar(a[0]) if a else XlErr("#VALUE!")
            if v is BLANK or isinstance(v, XlErr):
                return v
            n = _num(v)
            return n if isinstance(n, XlErr) else abs(n)
        if name in ("OR", "AND"):
            vals = [_truthy(x) for x in flat]
            if any(isinstance(x, XlErr) for x in vals):
                return next(x for x in vals if isinstance(x, XlErr))
            return any(vals) if name == "OR" else all(vals)
        if name == "IF":
            cond = _truthy(scalar(a[0]))
            if isinstance(cond, XlErr):
                return cond
            if cond:
                return a[1] if len(a) > 1 else True
            return a[2] if len(a) > 2 else False
        if name == "IFERROR":
            v = scalar(a[0])
            return a[1] if isinstance(v, XlErr) else v
        return XlErr("#NAME?")


def scalar(v):
    if isinstance(v, list):
        return v[0] if len(v) == 1 else XlErr("#VALUE!")
    return v


def _num(v):
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return XlErr("#VALUE!")
    return v


def _arith(op: str, a, b):
    for x in (a, b):
        if isinstance(x, XlErr):
            return x
    if a is BLANK or b is BLANK:
        return BLANK
    a, b = _num(a), _num(b)
    for x in (a, b):
        if isinstance(x, XlErr):
            return x
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        return XlErr("#DIV/0!") if b == 0 else a / b
    if op == "^":
        try:
            return float(a ** b)
        except (OverflowError, ZeroDivisionError, ValueError):
            return XlErr("#NUM!")
    raise WorkbookError(op)


def _compare(op: str, a, b):
    for x in (a, b):
        if isinstance(x, XlErr):
            return x
    if a is BLANK:
        a = "" if isinstance(b, str) else 0.0
    if b is BLANK:
        b = "" if isinstance(a, str) else 0.0
    if isinstance(a, str) != isinstance(b, str):
        return op == "<>"
    if isinstance(a, str):
        a, b = a.lower(), b.lower()
    return {"=": a == b, "<>": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]


def _truthy(v):
    if isinstance(v, XlErr):
        return v
    if v is BLANK:
        return False
    if isinstance(v, str):
        return XlErr("#VALUE!")
    return bool(v)


def _as_text(v) -> str:
    if v is BLANK:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return format(v, "g")
    return str(v)
