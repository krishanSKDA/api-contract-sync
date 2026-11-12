"""A lightweight Java source parser, good enough for Spring controllers and DTOs.

It is not a compiler front end. It understands the shapes that matter for an
HTTP contract: type declarations (class / record / enum / interface, nested to
any depth), their annotations, fields, methods, method parameters and generic
type references. Method bodies are skipped wholesale, which is what keeps it
fast and tolerant of syntax it does not model.

Standard library only, so it runs anywhere Python 3.10+ does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

IDENT = r"[A-Za-z_$][\w$]*"
MODIFIERS = {
    "public", "protected", "private", "static", "final", "abstract", "transient",
    "volatile", "synchronized", "native", "strictfp", "default", "sealed", "non-sealed",
}


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

@dataclass
class Annotation:
    name: str  # simple name, e.g. "GetMapping"
    raw_args: str = ""  # text between the parentheses, original (unmasked)

    def args(self) -> dict[str, str]:
        """Split `a = 1, b = "x"` into {"a": "1", "b": "\"x\""}; a bare value is "value"."""
        out: dict[str, str] = {}
        if not self.raw_args.strip():
            return out
        for part in split_top_level(self.raw_args, ","):
            m = re.match(r"\s*(" + IDENT + r")\s*=(?!=)\s*(.*)$", part, re.S)
            if m:
                out[m.group(1)] = m.group(2).strip()
            else:
                out.setdefault("value", part.strip())
        return out

    def get(self, *keys: str) -> str | None:
        a = self.args()
        for k in keys:
            if k in a:
                return a[k]
        return None

    def strings(self, *keys: str) -> list[str]:
        """String values of the first present key; arrays become several entries."""
        v = self.get(*keys)
        if v is None:
            return []
        v = v.strip()
        if v.startswith("{") and v.endswith("}"):
            return [s for p in split_top_level(v[1:-1], ",") if (s := concat_literals(p)) is not None]
        s = concat_literals(v)
        return [s] if s is not None else []

    def flag(self, key: str) -> str | None:
        v = self.get(key)
        return v.strip() if v is not None else None


@dataclass
class TypeRef:
    name: str  # as written, may be qualified: "java.util.List", "SalesController.SaleResponse"
    args: list["TypeRef"] = field(default_factory=list)
    dims: int = 0  # array dimensions
    wildcard: str | None = None  # "?" / "extends" / "super"

    @property
    def simple(self) -> str:
        return self.name.rsplit(".", 1)[-1]

    def __str__(self) -> str:
        s = self.name
        if self.args:
            s += "<" + ", ".join(map(str, self.args)) + ">"
        return s + "[]" * self.dims


@dataclass
class JParam:
    name: str
    type: TypeRef
    annotations: list[Annotation] = field(default_factory=list)

    def ann(self, name: str) -> Annotation | None:
        return find_ann(self.annotations, name)


@dataclass
class JField:
    name: str
    type: TypeRef
    annotations: list[Annotation]
    modifiers: set[str]
    initializer: str | None
    line: int
    doc: str | None = None

    def ann(self, name: str) -> Annotation | None:
        return find_ann(self.annotations, name)


@dataclass
class JMethod:
    name: str
    return_type: TypeRef | None  # None for constructors
    params: list[JParam]
    annotations: list[Annotation]
    modifiers: set[str]
    line: int
    doc: str | None = None

    def ann(self, name: str) -> Annotation | None:
        return find_ann(self.annotations, name)


@dataclass
class JType:
    kind: str  # class | record | enum | interface | annotation
    name: str
    qualified: str  # Outer.Inner (no package)
    package: str
    file: str
    line: int
    annotations: list[Annotation] = field(default_factory=list)
    modifiers: set[str] = field(default_factory=set)
    type_params: list[str] = field(default_factory=list)
    extends: TypeRef | None = None
    fields: list[JField] = field(default_factory=list)
    methods: list[JMethod] = field(default_factory=list)
    components: list[JParam] = field(default_factory=list)  # records
    enum_constants: list[str] = field(default_factory=list)
    nested: list["JType"] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    doc: str | None = None

    @property
    def fqn(self) -> str:
        return f"{self.package}.{self.qualified}" if self.package else self.qualified

    def ann(self, name: str) -> Annotation | None:
        return find_ann(self.annotations, name)


def find_ann(anns: list[Annotation], name: str) -> Annotation | None:
    for a in anns:
        if a.name == name:
            return a
    return None


# --------------------------------------------------------------------------- #
# Low-level text helpers
# --------------------------------------------------------------------------- #

def mask_source(src: str) -> tuple[str, dict[int, str]]:
    """Blank out comments and string/char literal contents, keeping offsets.

    Returns the masked text plus a map of javadoc comments keyed by the offset
    where the comment ended, so declarations can pick up their documentation.
    """
    out = list(src)
    docs: dict[int, str] = {}
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j == -1 else j
            for k in range(i, j):
                out[k] = " "
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            if src.startswith("/**", i):
                docs[j] = src[i:j]
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
        elif src.startswith('"""', i):
            j = src.find('"""', i + 3)
            j = n if j == -1 else j + 3
            for k in range(i + 3, j - 3):
                if out[k] != "\n":
                    out[k] = "x"
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == "\\":
                    j += 1
                elif src[j] == "\n":
                    break
                j += 1
            for k in range(i + 1, min(j, n)):
                out[k] = "x"
            i = j + 1
        else:
            i += 1
    return "".join(out), docs


def match_close(masked: str, i: int) -> int:
    """Index of the bracket closing the one at `i` (masked text, so no literals)."""
    pairs = {"{": "}", "(": ")", "[": "]", "<": ">"}
    open_c = masked[i]
    close_c = pairs[open_c]
    depth = 0
    for j in range(i, len(masked)):
        ch = masked[j]
        if ch == open_c:
            depth += 1
        elif ch == close_c:
            depth -= 1
            if depth == 0:
                return j
    return len(masked) - 1


def split_top_level(s: str, sep: str) -> list[str]:
    """Split on `sep` outside (), {}, [], <> and string literals."""
    parts, depth, cur, i = [], 0, [], 0
    in_str: str | None = None
    while i < len(s):
        c = s[i]
        if in_str:
            cur.append(c)
            if c == "\\" and i + 1 < len(s):
                cur.append(s[i + 1])
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in "\"'":
            in_str = c
            cur.append(c)
        elif c in "({[<":
            depth += 1
            cur.append(c)
        elif c in ")}]>":
            depth -= 1
            cur.append(c)
        elif c == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    if "".join(cur).strip():
        parts.append("".join(cur))
    return parts


def concat_literals(expr: str) -> str | None:
    """`"/api" + "/x"` -> "/api/x". None when the expression is not all literals."""
    lits = re.findall(r'"((?:[^"\\]|\\.)*)"', expr)
    if not lits:
        return None
    rest = re.sub(r'"((?:[^"\\]|\\.)*)"', "", expr)
    if rest.replace("+", "").strip():
        return None  # a constant reference is mixed in; can't resolve statically
    return "".join(lits)


def clean_doc(doc: str | None) -> str | None:
    if not doc:
        return None
    body = doc.strip()[3:-2]
    lines = [re.sub(r"^\s*\* ?", "", ln) for ln in body.splitlines()]
    text = " ".join(ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("@"))
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\{@\w+\s+#?([^}]*)\}", r"\1", text)
    return text.strip() or None


# --------------------------------------------------------------------------- #
# Declaration-header parsing
# --------------------------------------------------------------------------- #

class _Cursor:
    def __init__(self, masked: str, orig: str, start: int, end: int):
        self.m, self.o, self.i, self.end = masked, orig, start, end

    def ws(self) -> None:
        while self.i < self.end and self.m[self.i].isspace():
            self.i += 1

    def peek_ident(self) -> str | None:
        self.ws()
        m = re.compile(IDENT).match(self.m, self.i, self.end)
        return m.group(0) if m else None

    def ident(self) -> str | None:
        self.ws()
        m = re.compile(IDENT).match(self.m, self.i, self.end)
        if not m:
            return None
        self.i = m.end()
        return m.group(0)

    def qualified(self) -> str | None:
        name = self.ident()
        if name is None:
            return None
        while True:
            save = self.i
            self.ws()
            if self.i < self.end and self.m[self.i] == "." and not self.m.startswith("...", self.i):
                self.i += 1
                nxt = self.ident()
                if nxt is None:
                    self.i = save
                    break
                name += "." + nxt
            else:
                self.i = save
                break
        return name

    def annotations(self) -> list[Annotation]:
        anns = []
        while True:
            self.ws()
            if self.i < self.end and self.m[self.i] == "@" and not self.m.startswith("@interface", self.i):
                self.i += 1
                name = self.qualified() or ""
                self.ws()
                raw = ""
                if self.i < self.end and self.m[self.i] == "(":
                    j = match_close(self.m, self.i)
                    raw = self.o[self.i + 1:j]
                    self.i = j + 1
                anns.append(Annotation(name.rsplit(".", 1)[-1], raw))
            else:
                return anns

    def modifiers(self) -> set[str]:
        mods = set()
        while True:
            save = self.i
            word = self.ident()
            if word in MODIFIERS:
                mods.add(word)
                continue
            if word == "non" and self.m.startswith("-sealed", self.i):
                self.i += len("-sealed")
                continue
            self.i = save
            return mods

    def type_ref(self) -> TypeRef | None:
        self.annotations()  # type-use annotations, e.g. List<@Valid Foo>
        self.ws()
        if self.i < self.end and self.m[self.i] == "?":
            self.i += 1
            word = self.peek_ident()
            if word in ("extends", "super"):
                self.ident()
                bound = self.type_ref()
                if bound:
                    bound.wildcard = word
                return bound or TypeRef("?", wildcard="?")
            return TypeRef("?", wildcard="?")
        name = self.qualified()
        if name is None:
            return None
        ref = TypeRef(name)
        self.ws()
        if self.i < self.end and self.m[self.i] == "<":
            j = match_close(self.m, self.i)
            inner = self.m[self.i + 1:j]
            if inner.strip():  # "<>" diamond has no args
                for part_start, part in _offsets(inner, self.i + 1):
                    sub = _Cursor(self.m, self.o, part_start, part_start + len(part))
                    t = sub.type_ref()
                    if t:
                        ref.args.append(t)
            self.i = j + 1
        while True:
            self.ws()
            if self.m.startswith("[]", self.i):
                ref.dims += 1
                self.i += 2
            elif self.m.startswith("...", self.i):
                ref.dims += 1
                self.i += 3
            else:
                break
        return ref


def _offsets(inner: str, base: int) -> list[tuple[int, str]]:
    out, pos = [], 0
    for part in split_top_level(inner, ","):
        idx = inner.find(part, pos)
        out.append((base + idx, part))
        pos = idx + len(part)
    return out


def parse_type_string(s: str) -> TypeRef | None:
    masked, _ = mask_source(s)
    return _Cursor(masked, s, 0, len(s)).type_ref()


def _parse_params(masked: str, orig: str, start: int, end: int) -> list[JParam]:
    params = []
    for off, part in _offsets(masked[start:end], start):
        if not part.strip():
            continue
        c = _Cursor(masked, orig, off, off + len(part))
        anns = c.annotations()
        c.modifiers()
        anns += c.annotations()
        t = c.type_ref()
        name = c.ident()
        if t and name:
            params.append(JParam(name, t, anns))
    return params


# --------------------------------------------------------------------------- #
# File / type-body parsing
# --------------------------------------------------------------------------- #

TYPE_DECL = re.compile(r"\b(class|record|enum|interface|@interface)\s+(" + IDENT + r")")


class JavaFile:
    def __init__(self, path: Path, root: Path | None = None):
        self.path = path
        self.rel = (str(path.relative_to(root)) if root else str(path)).replace("\\", "/")
        self.orig = path.read_text(encoding="utf-8", errors="replace")
        self.masked, self.docs = mask_source(self.orig)
        pm = re.search(r"^\s*package\s+([\w.]+)\s*;", self.masked, re.M)
        self.package = pm.group(1) if pm else ""
        self.imports = re.findall(r"^\s*import\s+(?:static\s+)?([\w.*]+)\s*;", self.masked, re.M)
        self.types: list[JType] = []
        self._parse_members(0, len(self.masked), None, top=True)

    # -- helpers ---------------------------------------------------------------
    def line_of(self, i: int) -> int:
        return self.orig.count("\n", 0, i) + 1

    def doc_before(self, i: int) -> str | None:
        """Javadoc that ends right before offset i (only whitespace/annotations between)."""
        best = None
        for end, text in self.docs.items():
            if end <= i and not self.masked[end:i].strip() and (best is None or end > best[0]):
                best = (end, text)
        return clean_doc(best[1]) if best else None

    # -- members ---------------------------------------------------------------
    def _parse_members(self, start: int, end: int, owner: JType | None, top: bool = False) -> None:
        m = self.masked
        i = start
        member_start = start
        if owner and owner.kind == "enum":
            i = member_start = self._parse_enum_constants(start, end, owner)
        while i < end:
            c = m[i]
            if c == "(" or c == "[":
                i = match_close(m, i) + 1
                continue
            if c == "{":
                header_end = i
                j = match_close(m, i)
                header = m[member_start:header_end]
                # A field initializer containing a block (array init, lambda, anon class).
                if _has_top_level_assign(header) and not TYPE_DECL.search(header.split("=")[0]):
                    i = j + 1
                    continue
                self._handle_block(member_start, header_end, j, owner, top)
                i = member_start = j + 1
                continue
            if c == ";":
                if not top and owner is not None:
                    self._handle_statement(member_start, i, owner)
                i = member_start = i + 1
                continue
            if c == "}" and not top:
                member_start = i + 1
            i += 1

    def _parse_enum_constants(self, start: int, end: int, owner: JType) -> int:
        m = self.masked
        i, depth, cur_start = start, 0, start
        while i < end:
            c = m[i]
            if c in "({":
                i = match_close(m, i) + 1
                continue
            if c == "," or c == ";" or i == end - 1:
                seg_end = i if c in ",;" else i + 1
                cur = _Cursor(m, self.orig, cur_start, seg_end)
                cur.annotations()
                name = cur.ident()
                if name:
                    owner.enum_constants.append(name)
                if c == ";":
                    return i + 1
                cur_start = i + 1
            i += 1
        return end

    def _handle_block(self, hs: int, he: int, close: int, owner: JType | None, top: bool) -> None:
        header = self.masked[hs:he]
        td = TYPE_DECL.search(header)
        if td:
            self._parse_type(hs, he, close, td, owner)
            return
        if top or owner is None:
            return
        if "(" in header:
            meth = self._parse_method(hs, he, owner)
            if meth:
                owner.methods.append(meth)

    def _parse_type(self, hs: int, he: int, close: int, td: re.Match, owner: JType | None) -> None:
        m = self.masked
        cur = _Cursor(m, self.orig, hs, hs + td.start())
        anns = cur.annotations()
        mods = cur.modifiers()
        anns += cur.annotations()
        kind = {"@interface": "annotation"}.get(td.group(1), td.group(1))
        name = td.group(2)
        decl_at = hs + td.start()
        jt = JType(
            kind=kind,
            name=name,
            qualified=f"{owner.qualified}.{name}" if owner else name,
            package=self.package,
            file=self.rel,
            line=self.line_of(decl_at),
            annotations=anns,
            modifiers=mods,
            imports=self.imports,
            doc=self.doc_before(hs + len(m[hs:he]) - len(m[hs:he].lstrip())),
        )
        after = hs + td.end()
        c = _Cursor(m, self.orig, after, he)
        c.ws()
        if c.i < he and m[c.i] == "<":
            j = match_close(m, c.i)
            jt.type_params = [re.match(r"\s*(" + IDENT + ")", p).group(1) for p in split_top_level(m[c.i + 1:j], ",") if p.strip()]
            c.i = j + 1
        c.ws()
        if kind == "record" and c.i < he and m[c.i] == "(":
            j = match_close(m, c.i)
            jt.components = _parse_params(m, self.orig, c.i + 1, j)
            c.i = j + 1
        if c.peek_ident() == "extends" and kind == "class":
            c.ident()
            jt.extends = c.type_ref()
        (owner.nested if owner else self.types).append(jt)
        self._parse_members(he + 1, close, jt)

    def _parse_method(self, hs: int, he: int, owner: JType) -> JMethod | None:
        m = self.masked
        c = _Cursor(m, self.orig, hs, he)
        anns = c.annotations()
        mods = c.modifiers()
        anns += c.annotations()
        c.ws()
        if c.i < he and m[c.i] == "<":
            c.i = match_close(m, c.i) + 1
        anns += c.annotations()
        first = c.type_ref()
        if first is None:
            return None
        c.ws()
        if c.i < he and m[c.i] == "(":  # constructor: Name(...)
            name, ret = first.name, None
        else:
            name = c.ident()
            ret = first
            c.ws()
            if not name or c.i >= he or m[c.i] != "(":
                return None
        j = match_close(m, c.i)
        params = _parse_params(m, self.orig, c.i + 1, j)
        start = hs + len(m[hs:he]) - len(m[hs:he].lstrip())
        return JMethod(name, ret, params, anns, mods, self.line_of(start), self.doc_before(start))

    def _handle_statement(self, s: int, e: int, owner: JType) -> None:
        m = self.masked
        text = m[s:e]
        if not text.strip():
            return
        eq = _top_level_assign_index(text)
        decl = text if eq is None else text[:eq]
        probe = _Cursor(m, self.orig, s, s + len(decl))
        probe.annotations()
        probe.modifiers()
        probe.annotations()
        if "(" in m[probe.i:s + len(decl)]:  # abstract / interface method
            j = s + len(text) if eq is None else s + eq
            meth = self._parse_method(s, j, owner)
            if meth:
                owner.methods.append(meth)
            return
        c = _Cursor(m, self.orig, s, s + len(decl))
        anns = c.annotations()
        mods = c.modifiers()
        anns += c.annotations()
        t = c.type_ref()
        if t is None:
            return
        names = []
        while True:
            n = c.ident()
            if not n:
                break
            names.append(n)
            c.ws()
            while m.startswith("[]", c.i):
                t.dims += 1
                c.i += 2
                c.ws()
            if c.i < c.end and m[c.i] == ",":
                c.i += 1
                continue
            break
        init = self.orig[s + eq + 1:e].strip() if eq is not None else None
        start = s + len(text) - len(text.lstrip())
        doc = self.doc_before(start)
        for n in names:
            owner.fields.append(JField(n, t, anns, mods, init, self.line_of(start), doc))


def _top_level_assign_index(text: str) -> int | None:
    depth = 0
    for i, ch in enumerate(text):
        if ch in "(<[{":
            depth += 1
        elif ch in ")>]}":
            depth -= 1
        elif ch == "=" and depth == 0:
            prev = text[i - 1] if i else ""
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if prev not in "=!<>" and nxt != "=":
                return i
    return None


def _has_top_level_assign(header: str) -> bool:
    return _top_level_assign_index(header) is not None


# --------------------------------------------------------------------------- #
# Project index
# --------------------------------------------------------------------------- #

class JavaProject:
    """All types under a source root, with name resolution."""

    def __init__(self, root: Path, exclude: tuple[str, ...] = ("test", "build", "target", "generated")):
        self.root = root
        self.files: list[JavaFile] = []
        self.errors: list[str] = []
        kt_files = sorted(root.rglob("*.kt"))
        if kt_files:
            try:
                from .kotlin_parser import KotlinFile
            except ImportError:
                from kotlin_parser import KotlinFile  # noqa: E402
        for p in sorted(root.rglob("*.java")) + kt_files:
            parts = set(p.relative_to(root).parts)
            if parts & set(exclude):
                continue
            try:
                self.files.append(KotlinFile(p, root) if p.suffix == ".kt" else JavaFile(p, root))
            except Exception as e:  # keep going; one odd file shouldn't sink the run
                self.errors.append(f"{p}: {e}")
        self.by_fqn: dict[str, JType] = {}
        self.by_simple: dict[str, list[JType]] = {}
        self.by_qualified: dict[str, list[JType]] = {}
        for f in self.files:
            for t in f.types:
                self._index(t)

    def _index(self, t: JType) -> None:
        self.by_fqn[t.fqn] = t
        self.by_simple.setdefault(t.name, []).append(t)
        self.by_qualified.setdefault(t.qualified, []).append(t)
        for n in t.nested:
            self._index(n)

    def all_types(self):
        return list(self.by_fqn.values())

    def resolve(self, name: str, context: JType | None) -> JType | None:
        """Resolve a type name as written in `context` to a project type, or None."""
        if name in self.by_fqn:
            return self.by_fqn[name]
        if context is not None:
            # Nested inside the context or any of its enclosing types.
            parts = context.qualified.split(".")
            for k in range(len(parts), 0, -1):
                cand = f"{context.package}.{'.'.join(parts[:k])}.{name}" if context.package else f"{'.'.join(parts[:k])}.{name}"
                if cand in self.by_fqn:
                    return self.by_fqn[cand]
            # Explicit import.
            for imp in context.imports:
                if imp.endswith("." + name.split(".")[0]):
                    cand = imp + name[len(name.split(".")[0]):]
                    if cand in self.by_fqn:
                        return self.by_fqn[cand]
            # Same package.
            cand = f"{context.package}.{name}" if context.package else name
            if cand in self.by_fqn:
                return self.by_fqn[cand]
        hits = self.by_qualified.get(name) or self.by_simple.get(name.rsplit(".", 1)[-1]) or []
        if len(hits) == 1:
            return hits[0]
        if hits and context is not None:
            same_pkg = [h for h in hits if h.package == context.package]
            if len(same_pkg) == 1:
                return same_pkg[0]
        return hits[0] if hits else None
