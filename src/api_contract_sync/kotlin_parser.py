"""A lightweight Kotlin source parser for Spring controllers and DTOs.

It produces the same model as java_parser (JType / JField / JMethod / JParam /
TypeRef), translating Kotlin types to their Java equivalents, so extract_spring's
Spring MVC and Jackson rules apply unchanged:

  * `Int` -> int (non-null), `Int?` -> Integer; `String` (non-null) gets a synthetic
    @KotlinNonNull annotation; `List`/`MutableList` -> List; `Array<T>` -> T[]; `Unit` -> void
  * `data class Order(val id: Long?, val name: String)` -> a class whose constructor
    `val`/`var` parameters are public fields (Jackson's Kotlin module serializes them)
  * a nullable or defaulted @RequestParam becomes Optional (Spring treats it as optional)
  * use-site targets are dropped: `@field:JsonProperty("x")` -> @JsonProperty("x")
  * annotation arrays `["/a", "/b"]` / `arrayOf(...)` -> Java's `{"/a", "/b"}`

Function bodies are skipped. Standard library only.
"""

from __future__ import annotations

import re
from pathlib import Path

try:
    from .java_parser import (Annotation, JField, JMethod, JParam, JType, TypeRef, clean_doc, mask_source,
                              match_close, split_top_level)
except ImportError:
    from java_parser import (Annotation, JField, JMethod, JParam, JType, TypeRef, clean_doc, mask_source,  # noqa: E402
                             match_close, split_top_level)

IDENT = r"[A-Za-z_][\w]*"
KMODS = {
    "public", "private", "protected", "internal", "open", "final", "abstract", "sealed", "data", "enum",
    "annotation", "inner", "value", "override", "suspend", "inline", "operator", "infix", "tailrec",
    "external", "lateinit", "const", "companion", "vararg", "noinline", "crossinline", "expect", "actual",
}
USE_SITE = {"field", "get", "set", "param", "property", "setparam", "delegate", "file", "receiver"}
NON_NULL = "KotlinNonNull"  # synthetic annotation: a non-null Kotlin type

BOXED = {"Int": "Integer", "Long": "Long", "Short": "Short", "Byte": "Byte", "Double": "Double",
         "Float": "Float", "Boolean": "Boolean", "Char": "Character"}
PRIM = {"Int": "int", "Long": "long", "Short": "short", "Byte": "byte", "Double": "double",
        "Float": "float", "Boolean": "boolean", "Char": "char"}
PRIM_TO_BOXED = {PRIM[k]: BOXED[k] for k in PRIM}
RENAME = {
    "Any": "Object", "Unit": "void", "Nothing": "void",
    "MutableList": "List", "ArrayList": "List", "Collection": "List", "MutableCollection": "List", "Iterable": "List",
    "Sequence": "List", "MutableSet": "Set", "HashSet": "Set", "LinkedHashSet": "Set",
    "MutableMap": "Map", "HashMap": "Map", "LinkedHashMap": "Map",
    "Flow": "List",  # kotlinx.coroutines Flow<T> from a controller is written as a JSON array
}
PRIM_ARRAYS = {"IntArray": "int", "LongArray": "long", "ShortArray": "short", "ByteArray": "byte",
               "DoubleArray": "double", "FloatArray": "float", "BooleanArray": "boolean", "CharArray": "char"}
KDECL = re.compile(r"(?<![\w$.@:])(class|interface|object|fun|val|var|init|constructor)\b")


def parse_ktype(text: str) -> tuple[TypeRef, bool]:
    """Kotlin type text -> (Java-equivalent TypeRef, nullable)."""
    t = re.sub(r"@[\w.:]+(\([^)]*\))?\s*", "", text.strip())  # type-use annotations
    nullable = False
    while t.endswith("?"):
        nullable, t = True, t[:-1].strip()
    if t.startswith("(") and t.endswith(")") and "->" not in t:
        inner, n2 = parse_ktype(t[1:-1])
        return inner, nullable or n2
    if "->" in t or not t:  # function type
        return TypeRef("Object"), nullable
    if t == "*":
        return TypeRef("?", wildcard="?"), True
    t = re.sub(r"^(in|out)\s+", "", t)
    name, args = t, []
    lt = t.find("<")
    if lt != -1 and t.endswith(">"):
        name = t[:lt].strip()
        args = [parse_ktype(a)[0] for a in split_top_level(t[lt + 1:-1], ",") if a.strip()]
    simple = name.rsplit(".", 1)[-1]
    if simple in PRIM_ARRAYS:
        return TypeRef(PRIM_ARRAYS[simple], dims=1), nullable
    if simple == "Array" and args:
        el = args[0]
        el = TypeRef(BOXED.get(el.name, el.name), el.args, el.dims + 1, el.wildcard)
        return el, nullable
    if simple in PRIM:
        if args:
            return TypeRef(BOXED[simple]), nullable
        return TypeRef(BOXED[simple] if nullable else PRIM[simple]), nullable
    if simple in RENAME:
        name = RENAME[simple]
    # generic arguments are always boxed in Java: List<Int> -> List<Integer>
    args = [TypeRef(PRIM_TO_BOXED.get(a.name, a.name) if not a.dims else a.name, a.args, a.dims, a.wildcard)
            for a in args]
    return TypeRef(name, args), nullable


def kotlin_array_args(raw: str) -> str:
    """`["/a", "/b"]` and `arrayOf("/a")` -> `{"/a", "/b"}` so java_parser's Annotation reads them."""
    masked, _ = mask_source(raw)
    out = list(raw)
    for m in re.finditer(r"\b(?:arrayOf|listOf)\s*\(", masked):
        o = m.end() - 1
        c = match_close(masked, o)
        for k in range(m.start(), o):
            out[k] = " "
        out[o], out[c] = "{", "}"
    for k, ch in enumerate(masked):
        if ch == "[":
            out[k] = "{"
        elif ch == "]":
            out[k] = "}"
    return "".join(out)


class KotlinFile:
    def __init__(self, path: Path, root: Path | None = None):
        self.path = path
        self.rel = (str(path.relative_to(root)) if root else str(path)).replace("\\", "/")
        self.orig = path.read_text(encoding="utf-8", errors="replace")
        self.m, self.docs = mask_source(self.orig)
        pm = re.search(r"^\s*package\s+([\w.]+)", self.m, re.M)
        self.package = pm.group(1) if pm else ""
        self.imports = re.findall(r"^\s*import\s+([\w.*]+)", self.m, re.M)
        self.types: list[JType] = []
        self._body(0, len(self.m), None)

    # ------------------------------------------------------------------ helpers
    def line_of(self, i: int) -> int:
        return self.orig.count("\n", 0, i) + 1

    def doc_before(self, i: int) -> str | None:
        best = None
        for end, text in self.docs.items():
            between = self.m[end:i]
            if end <= i and not re.sub(r"@[\w.:]+(\([^)]*\))?|\b(" + "|".join(KMODS) + r")\b", "", between).strip() \
                    and (best is None or end > best[0]):
                best = (end, text)
        return clean_doc(best[1]) if best else None

    def ws(self, i: int, end: int, newlines: bool = True) -> int:
        while i < end and (self.m[i] in " \t\r" or (newlines and self.m[i] == "\n")):
            i += 1
        return i

    def ident(self, i: int, end: int) -> tuple[str | None, int]:
        i = self.ws(i, end)
        mm = re.compile(IDENT).match(self.m, i, end)
        return (mm.group(0), mm.end()) if mm else (None, i)

    def annotation(self, i: int, end: int) -> tuple[Annotation, int]:
        """At '@': parse one annotation, dropping a use-site target (@field:, @get:, ...)."""
        i += 1
        mm = re.compile(r"(" + IDENT + r")\s*:(?!:)").match(self.m, i, end)
        if mm and mm.group(1) in USE_SITE:
            i = mm.end()
        mm = re.compile(r"[\w.]+").match(self.m, i, end)
        name = mm.group(0) if mm else ""
        i = mm.end() if mm else i
        raw = ""
        if i < end and self.m[i] == "(":
            c = match_close(self.m, i)
            raw = kotlin_array_args(self.orig[i + 1:c])
            i = c + 1
        return Annotation(name.rsplit(".", 1)[-1], raw), i

    def prefix(self, seg: int, kw: int) -> tuple[list[Annotation], set[str], int]:
        """Annotations and modifiers between the previous declaration and keyword `kw`.
        Anything unrecognised resets them (it belonged to something we skipped)."""
        anns, mods, i, first = [], set(), seg, None
        while i < kw:
            i = self.ws(i, kw)
            if i >= kw:
                break
            if self.m[i] == "@":
                first = i if first is None else first
                a, i = self.annotation(i, kw)
                anns.append(a)
                continue
            w, j = self.ident(i, kw)
            if w in KMODS:
                first = i if first is None else first
                mods.add(w)
                i = j
                continue
            anns, mods, first = [], set(), None
            if self.m[i] in "([{":
                i = match_close(self.m, i) + 1
            else:
                i = j if j > i else i + 1
        return anns, mods, (first if first is not None else kw)

    def line_end(self, i: int, end: int) -> int:
        """End of a statement starting at i: the first newline at bracket depth 0 whose
        next line does not continue the expression (leading '.', '?.', operator, ...)."""
        while i < end:
            ch = self.m[i]
            if ch in "([{":
                i = match_close(self.m, i) + 1
                continue
            if ch == ";":
                return i + 1
            if ch == "\n":
                j = self.ws(i, end)
                if j < end and (self.m[j] in ".?:+-*/%&|=<>" or self.m.startswith("as ", j)) \
                        and not self.m.startswith("@", j):
                    i = j
                    continue
                return i
            i += 1
        return end

    def type_text_until(self, i: int, end: int, stops: str) -> tuple[str, int]:
        """Read a type expression up to one of `stops` (or a newline) at depth 0."""
        start = i
        while i < end:
            ch = self.m[i]
            if ch in "(<[":
                i = match_close(self.m, i) + 1
                continue
            if ch in stops or ch == "\n" or (ch == "=" and "=" in stops) or self.m.startswith("by ", i):
                break
            i += 1
        return self.orig[start:i].strip(), i

    # ------------------------------------------------------------------ bodies
    def _body(self, start: int, end: int, owner: JType | None) -> None:
        i = seg = start
        while i < end:
            ch = self.m[i]
            if ch == "@":  # annotation (with its arguments) belongs to the next declaration: keep seg
                _, i = self.annotation(i, end)
                continue
            if ch == "{":
                i = seg = match_close(self.m, i) + 1  # init {...}, companion object {...}, stray blocks
                continue
            if ch in "([":
                i = match_close(self.m, i) + 1
                continue
            mm = KDECL.match(self.m, i)
            if not mm:
                i += 1
                continue
            kw = mm.group(1)
            if kw in ("class", "interface", "object"):
                j = self._class(seg, i, mm.end(), kw, owner)
            elif kw == "fun":
                j = self._fun(seg, i, mm.end(), owner)
            elif kw in ("val", "var"):
                j = self._prop(seg, i, mm.end(), owner)
            else:  # init { } / secondary constructor(...) { }
                j = self.line_end(mm.end(), end)
                k = self.ws(j, end)
                if k < end and self.m[k] == "{":
                    j = match_close(self.m, k) + 1
            i = seg = max(j, i + 1)

    def _class(self, seg: int, kw_at: int, after: int, kw: str, owner: JType | None) -> int:
        anns, mods, decl_start = self.prefix(seg, kw_at)
        name, i = self.ident(after, len(self.m))
        if name is None:  # companion object { ... } / anonymous object
            k = self.ws(after, len(self.m))
            return match_close(self.m, k) + 1 if k < len(self.m) and self.m[k] == "{" else after
        kind = "enum" if "enum" in mods else "annotation" if "annotation" in mods else \
            "interface" if kw == "interface" else "class"
        jt = JType(kind=kind, name=name, qualified=f"{owner.qualified}.{name}" if owner else name,
                   package=self.package, file=self.rel, line=self.line_of(kw_at), annotations=anns,
                   modifiers=mods | ({"public"} if not mods & {"private", "internal", "protected"} else set()),
                   imports=self.imports, doc=self.doc_before(decl_start))
        n = len(self.m)
        i = self.ws(i, n, newlines=False)
        if i < n and self.m[i] == "<":
            c = match_close(self.m, i)
            jt.type_params = [re.match(r"\s*(?:in|out|reified)?\s*(" + IDENT + ")", p).group(1)
                              for p in split_top_level(self.m[i + 1:c], ",") if p.strip()]
            i = c + 1
        # primary constructor: [annotations] [modifiers] [constructor] ( ... )
        j = self.ws(i, n, newlines=False)
        while j < n and (self.m[j] == "@" or re.match(r"(private|protected|internal|public|constructor)\b", self.m[j:j + 12])):
            if self.m[j] == "@":
                _, j = self.annotation(j, n)
            else:
                j = re.compile(r"\w+").match(self.m, j).end()
            j = self.ws(j, n, newlines=False)
        if j < n and self.m[j] == "(":
            c = match_close(self.m, j)
            for p in self._params(j + 1, c, properties=True):
                jt.fields.append(p)
            i = c + 1
        # supertypes
        j = self.ws(i, n, newlines=False)
        if j < n and self.m[j] == ":":
            text, i = self.type_text_until(j + 1, n, "{")
            for st in split_top_level(text, ","):
                st = st.strip()
                if re.search(r"\)\s*$", st):  # Base(...) -> the superclass
                    jt.extends = parse_ktype(st[:st.index("(")])[0]
                    break
        j = self.ws(i, n)
        end = i
        if j < n and self.m[j] == "{":
            c = match_close(self.m, j)
            body_start = j + 1
            if kind == "enum":
                body_start = self._enum_entries(body_start, c, jt)
            (owner.nested if owner else self.types).append(jt)
            self._body(body_start, c, jt)
            end = c + 1
        else:
            (owner.nested if owner else self.types).append(jt)
        return end

    def _enum_entries(self, start: int, end: int, jt: JType) -> int:
        i, cur = start, start
        while i < end:
            ch = self.m[i]
            if ch in "({":
                i = match_close(self.m, i) + 1
                continue
            if ch in ",;" or i == end - 1:
                seg_end = i if ch in ",;" else i + 1
                k = cur
                while True:
                    k = self.ws(k, seg_end)
                    if k < seg_end and self.m[k] == "@":
                        _, k = self.annotation(k, seg_end)
                    else:
                        break
                name, _ = self.ident(k, seg_end)
                if name and name not in ("fun", "val", "var"):
                    jt.enum_constants.append(name)
                if ch == ";":
                    return i + 1
                cur = i + 1
            if KDECL.match(self.m, i):
                return cur
            i += 1
        return end

    def _params(self, start: int, end: int, properties: bool) -> list:
        """Constructor (properties=True -> JField for val/var params) or function parameters."""
        out = []
        for part in split_top_level(self.m[start:end], ","):
            off = self.m.find(part, start)
            start = off + len(part)
            pend = off + len(part)
            i, anns, mods, is_prop = off, [], set(), False
            while True:
                i = self.ws(i, pend)
                if i < pend and self.m[i] == "@":
                    a, i = self.annotation(i, pend)
                    anns.append(a)
                    continue
                w, j = self.ident(i, pend)
                if w in ("val", "var"):
                    is_prop, i = True, j
                    continue
                if w in KMODS:
                    mods.add(w)
                    i = j
                    continue
                break
            name, i = self.ident(i, pend)
            i = self.ws(i, pend)
            if not name or i >= pend or self.m[i] != ":":
                continue
            eq = _top_level_eq(self.m, i + 1, pend)
            ttext = self.orig[i + 1:eq if eq is not None else pend].strip()
            default = self.orig[eq + 1:pend].strip() if eq is not None else None
            ref, nullable = parse_ktype(ttext)
            if properties:
                if not is_prop:
                    continue
                if not nullable and default is None and ref.name not in PRIM.values():
                    anns = anns + [Annotation(NON_NULL)]
                vis = "private" if "private" in mods else "protected" if "protected" in mods else "public"
                out.append(JField(name, ref, anns, {vis} | ({"final"} if not is_prop else set()),
                                  default if default is not None else ("null" if nullable else None),
                                  self.line_of(off + len(part) - len(part.lstrip())), self.doc_before(off)))
            else:
                if (nullable or default is not None) and (find(anns, "RequestParam") or find(anns, "RequestHeader")):
                    ref = TypeRef("Optional", [ref])  # Spring: nullable/defaulted Kotlin params are optional
                out.append(JParam(name, ref, anns))
        return out

    def _fun(self, seg: int, kw_at: int, after: int, owner: JType | None) -> int:
        anns, mods, decl_start = self.prefix(seg, kw_at)
        n = len(self.m)
        i = self.ws(after, n)
        if i < n and self.m[i] == "<":
            i = match_close(self.m, i) + 1
        name_start = self.ws(i, n)
        mm = re.compile(r"[\w.<>, ?]+?(?=\s*\()").match(self.m, name_start)
        if not mm:
            return self.line_end(after, n)
        full = mm.group(0).strip()
        name = full.rsplit(".", 1)[-1]
        p = self.ws(mm.end(), n)
        if p >= n or self.m[p] != "(":
            return self.line_end(after, n)
        c = match_close(self.m, p)
        params = self._params(p + 1, c, properties=False)
        i = self.ws(c + 1, n, newlines=False)
        ret = None
        if i < n and self.m[i] == ":":
            text, i = self.type_text_until(i + 1, n, "{=")
            ret = parse_ktype(text)[0] if text else None
        j = self.ws(i, n, newlines=False)
        k = self.ws(i, n)
        if k < n and self.m[k] == "{":
            end = match_close(self.m, k) + 1
            ret = ret or TypeRef("void")
        elif j < n and self.m[j] == "=":
            end = self.line_end(self.ws(j + 1, n), n)
            ret = ret or TypeRef("Object")
        else:
            end = i
        if owner is not None and "." not in full:  # skip extension functions
            vis = "private" if "private" in mods else "protected" if "protected" in mods else "public"
            owner.methods.append(JMethod(name, ret, params, anns, (mods - {"private", "protected"}) | {vis},
                                         self.line_of(kw_at), self.doc_before(decl_start)))
        return end

    def _prop(self, seg: int, kw_at: int, after: int, owner: JType | None) -> int:
        anns, mods, decl_start = self.prefix(seg, kw_at)
        n = len(self.m)
        end = self.line_end(after, n)
        name, i = self.ident(after, end)
        i = self.ws(i, end)
        if owner is None or not name or (i < end and self.m[i] == "."):  # top-level or extension property
            return end
        ttext, init = "", None
        if i < end and self.m[i] == ":":
            ttext, i = self.type_text_until(i + 1, end, "=")
        i = self.ws(i, end)
        if i < end and self.m[i] == "=":
            init = self.orig[i + 1:end].strip()
        if ttext:
            ref, nullable = parse_ktype(ttext)
        else:  # inferred from a literal initializer
            lit = (init or "").strip()
            ref, nullable = (TypeRef("String"), False) if lit.startswith('"') else \
                (TypeRef("boolean"), False) if lit in ("true", "false") else \
                (TypeRef("int"), False) if re.fullmatch(r"-?\d+", lit) else (TypeRef("Object"), True)
        if not nullable and init is None and ref.name not in PRIM.values():
            anns = anns + [Annotation(NON_NULL)]  # lateinit / abstract / computed (get() = ...) non-null
        vis = "private" if "private" in mods else "protected" if "protected" in mods else "public"
        owner.fields.append(JField(name, ref, anns, {vis}, init if init is not None else ("null" if nullable else None),
                                   self.line_of(kw_at), self.doc_before(decl_start)))
        return end


def find(anns: list[Annotation], name: str) -> Annotation | None:
    return next((a for a in anns if a.name == name), None)


def _top_level_eq(m: str, start: int, end: int) -> int | None:
    depth = 0
    for k in range(start, end):
        ch = m[k]
        if ch in "(<[{":
            depth += 1
        elif ch in ")>]}":
            depth -= 1
        elif ch == "=" and depth == 0 and m[k + 1:k + 2] != "=" and m[k - 1:k] not in ("=", "!", "<", ">"):
            return k
    return None
