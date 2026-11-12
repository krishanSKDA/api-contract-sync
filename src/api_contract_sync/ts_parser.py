"""Lightweight TypeScript / JavaScript scanner for drift detection.

Reads .ts/.tsx/.mts/.cts, plain .js/.jsx/.mjs/.cjs, and the <script> blocks of
.vue and .svelte files. Plain JavaScript has no types, so for it only URL, method,
text-vs-JSON and request-body-key checks apply.

Finds, across a frontend source tree:
  * interface / type-alias declarations and their members
  * HTTP call sites: fetch(), axios.<verb>(), axios-instance.<verb>() and any
    extra wrapper functions named on the command line
  * for each call site: URL (resolved through local constants and template
    literals), HTTP method, the TS type the response is cast to, and the TS
    type / object literal sent as the body

It is heuristic by design. Anything it cannot resolve is reported as
"unresolved" rather than guessed, so the caller can look at it by hand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

IDENT = r"[A-Za-z_$][\w$]*"
PLACEHOLDER = "\u0000"  # stands in for an unresolved ${expr} in a URL
HTTP_VERBS = ("get", "post", "put", "delete", "patch", "head", "options")


# --------------------------------------------------------------------------- #
# Masking
# --------------------------------------------------------------------------- #

def mask_ts(src: str) -> tuple[str, str]:
    """Return (no_comments, full_mask).

    no_comments: comments blanked, literals intact (for reading URLs/types).
    full_mask:   comments AND literal contents blanked (for bracket matching).
    Offsets are preserved in both.
    """
    nc = list(src)
    fm = list(src)
    n = len(src)

    def scan_code(i: int, stop_at_brace: bool) -> int:
        depth = 0
        prev_sig = ""
        while i < n:
            c = src[i]
            if src.startswith("//", i):
                j = src.find("\n", i)
                j = n if j == -1 else j
                for k in range(i, j):
                    nc[k] = fm[k] = " "
                i = j
                continue
            if src.startswith("/*", i):
                j = src.find("*/", i + 2)
                j = n if j == -1 else j + 2
                for k in range(i, j):
                    if src[k] != "\n":
                        nc[k] = fm[k] = " "
                i = j
                continue
            if c in "'\"":
                j = i + 1
                while j < n and src[j] != c and src[j] != "\n":
                    j += 2 if src[j] == "\\" else 1
                for k in range(i + 1, min(j, n)):
                    fm[k] = "x"
                i = j + 1
                prev_sig = "a"
                continue
            if c == "`":
                i = scan_template(i + 1)
                prev_sig = "a"
                continue
            if c == "/" and (prev_sig == "" or prev_sig in "(,=:[!&|?{};+-*%<>~^" or prev_sig == "return"):
                j, in_class = i + 1, False
                while j < n and src[j] != "\n":
                    if src[j] == "\\":
                        j += 2
                        continue
                    if src[j] == "[":
                        in_class = True
                    elif src[j] == "]":
                        in_class = False
                    elif src[j] == "/" and not in_class:
                        break
                    j += 1
                if j < n and src[j] == "/":
                    for k in range(i + 1, j):
                        fm[k] = "x"
                    i = j + 1
                    prev_sig = "a"
                    continue
            if c == "{":
                depth += 1
            elif c == "}":
                if depth == 0 and stop_at_brace:
                    return i
                depth -= 1
            if not c.isspace():
                if c.isalnum() or c in "_$":
                    m = re.compile(r"[\w$]+").match(src, i)
                    prev_sig = "return" if m.group(0) == "return" else "a"
                    i = m.end()
                    continue
                prev_sig = c
            i += 1
        return i

    def scan_template(i: int) -> int:
        while i < n:
            c = src[i]
            if c == "\\":
                fm[i] = "x"
                if i + 1 < n:
                    fm[i + 1] = "x"
                i += 2
                continue
            if c == "`":
                return i + 1
            if src.startswith("${", i):
                j = scan_code(i + 2, stop_at_brace=True)
                i = j + 1
                continue
            if c != "\n":
                fm[i] = "x"
            i += 1
        return i

    scan_code(0, stop_at_brace=False)
    return "".join(nc), "".join(fm)


def match_close(masked: str, i: int) -> int:
    pairs = {"{": "}", "(": ")", "[": "]", "<": ">"}
    o, c = masked[i], pairs[masked[i]]
    depth = 0
    for j in range(i, len(masked)):
        ch = masked[j]
        if ch == o:
            depth += 1
        elif ch == c and not (c == ">" and masked[j - 1] == "="):
            depth -= 1
            if depth == 0:
                return j
    return len(masked) - 1


def split_top(s: str, seps: str) -> list[str]:
    parts, depth, cur, q = [], 0, [], None
    i = 0
    while i < len(s):
        ch = s[i]
        if q:
            cur.append(ch)
            if ch == "\\" and i + 1 < len(s):
                cur.append(s[i + 1])
                i += 2
                continue
            if ch == q:
                q = None
        elif ch in "'\"`":
            q = ch
            cur.append(ch)
        elif ch in "({[<":
            depth += 1
            cur.append(ch)
        elif ch in ")}]>" and not (ch == ">" and i and s[i - 1] == "="):
            depth -= 1
            cur.append(ch)
        elif ch in seps and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    if "".join(cur).strip():
        parts.append("".join(cur))
    return parts


# --------------------------------------------------------------------------- #
# Type model
# --------------------------------------------------------------------------- #

@dataclass
class TsMember:
    name: str
    type_text: str
    optional: bool
    line: int


@dataclass
class TsDecl:
    name: str
    file: str
    line: int
    members: list[TsMember] | None  # None when not an object shape
    alias_text: str | None = None  # for non-object type aliases
    extends: list[str] = field(default_factory=list)


def classify(text: str) -> dict:
    """TS type text -> {"kind": ..., "nullable": bool, ...}."""
    t = text.strip()
    while t.startswith("(") and match_close(t, 0) == len(t) - 1:
        t = t[1:-1].strip()
    t = re.sub(r"^\|\s*", "", t)
    parts = [p.strip() for p in split_top(t, "|") if p.strip()]
    nullable = any(p in ("null", "undefined") for p in parts)
    parts = [p for p in parts if p not in ("null", "undefined")]
    if not parts:
        return {"kind": "null", "nullable": True}
    if len(parts) > 1:
        if all(re.fullmatch(r"'[^']*'|\"[^\"]*\"", p) for p in parts):
            return {"kind": "string", "literals": [p[1:-1] for p in parts], "nullable": nullable}
        if all(p in ("true", "false", "boolean") for p in parts):
            return {"kind": "boolean", "nullable": nullable}
        return {"kind": "union", "options": [classify(p) for p in parts], "nullable": nullable}
    p = parts[0]
    out: dict
    if re.fullmatch(r"'[^']*'|\"[^\"]*\"", p):
        out = {"kind": "string", "literals": [p[1:-1]]}
    elif re.fullmatch(r"-?\d+(\.\d+)?", p):
        out = {"kind": "number"}
    elif p in ("true", "false", "boolean"):
        out = {"kind": "boolean"}
    elif p == "string" or p.startswith("`"):
        out = {"kind": "string"}
    elif p in ("number", "bigint"):
        out = {"kind": "number"}
    elif p in ("any", "unknown", "object", "never", "{}", "Object", "void"):
        out = {"kind": "unknown"}
    elif p == "Date":
        out = {"kind": "date"}
    elif p.endswith("[]"):
        out = {"kind": "array", "items": classify(p[:-2])}
    elif p.startswith("{"):
        out = {"kind": "object", "members": parse_members(p[1:match_close(p, 0)], 0, "")}
        idx = [m for m in out["members"] if m.name == "__index__"]
        if idx and len(out["members"]) == 1:
            out = {"kind": "map", "values": classify(idx[0].type_text)}
    elif p.startswith("["):
        out = {"kind": "array", "items": {"kind": "unknown"}}  # tuple
    else:
        m = re.fullmatch(r"(" + IDENT + r"(?:\." + IDENT + r")*)\s*(<(.*)>)?", p, re.S)
        if not m:
            if "&" in p:
                return {"kind": "intersection", "parts": [classify(x) for x in split_top(p, "&")], "nullable": nullable}
            return {"kind": "unknown", "nullable": nullable}
        name, args = m.group(1), [a.strip() for a in split_top(m.group(3) or "", ",")]
        if name in ("Array", "ReadonlyArray", "Set") and args:
            out = {"kind": "array", "items": classify(args[0])}
        elif name in ("Record", "Map") and len(args) == 2:
            out = {"kind": "map", "values": classify(args[1])}
        elif name in ("Partial", "Readonly", "Required", "NonNullable") and args:
            inner = classify(args[0])
            if name == "Partial":
                inner["partial"] = True
            out = inner
        elif name in ("Omit", "Pick") and args:
            inner = classify(args[0])
            keys = re.findall(r"'([^']*)'|\"([^\"]*)\"", args[1]) if len(args) > 1 else []
            inner[name.lower()] = [a or b for a, b in keys]
            out = inner
        elif name == "Promise" and args:
            out = classify(args[0])
        elif name in ("Blob", "File", "ArrayBuffer", "FormData"):
            out = {"kind": "binary"}
        else:
            out = {"kind": "ref", "name": name.rsplit(".", 1)[-1], "args": args}
    if "&" in p and out.get("kind") in ("ref", "unknown"):
        parts_i = split_top(p, "&")
        if len(parts_i) > 1:
            out = {"kind": "intersection", "parts": [classify(x) for x in parts_i]}
    out["nullable"] = nullable or out.get("nullable", False)
    return out


def parse_members(body: str, base_offset: int, src_for_lines: str) -> list[TsMember]:
    """Parse `a: T; b?: U, readonly c: V` (also newline-separated)."""
    _, fm = mask_ts(body)
    members, start, depth, i = [], 0, 0, 0
    chunks: list[tuple[int, int]] = []
    while i < len(body):
        ch = fm[i]
        if ch in "({[<":
            depth += 1
        elif ch in ")}]>" and not (ch == ">" and i and fm[i - 1] == "="):
            depth -= 1
        elif depth == 0 and ch in ";,":
            chunks.append((start, i))
            start = i + 1
        elif depth == 0 and ch == "\n":
            rest = body[i + 1:]
            cur = body[start:i]
            if ":" in cur and re.match(r"\s*(readonly\s+)?(['\"]?)[\w$]+\2\??\s*[:(]|\s*\[", rest) and not re.search(r"[|&]\s*$", cur):
                chunks.append((start, i))
                start = i + 1
        i += 1
    chunks.append((start, len(body)))
    for a, b in chunks:
        raw = body[a:b]
        if not raw.strip():
            continue
        lead = len(raw) - len(raw.lstrip())
        line = (src_for_lines.count("\n", 0, base_offset + a + lead) + 1) if src_for_lines else 0
        m = re.match(r"\s*(?:readonly\s+)?(['\"]?)([\w$-]+)\1(\?)?\s*:\s*(.+)$", raw, re.S)
        if m:
            members.append(TsMember(m.group(2), m.group(4).strip(), bool(m.group(3)), line))
            continue
        m = re.match(r"\s*\[\s*\w+\s*:\s*(?:string|number)\s*\]\s*\??\s*:\s*(.+)$", raw, re.S)
        if m:
            members.append(TsMember("__index__", m.group(1).strip(), True, line))
    return members


# --------------------------------------------------------------------------- #
# Call sites
# --------------------------------------------------------------------------- #

@dataclass
class CallSite:
    file: str
    line: int
    client: str  # "fetch" | "axios:<instance>" | "<wrapper>"
    method: str | None  # None = could not determine
    raw_url: str
    path: str | None  # normalized, "{}" for params; None = unresolved
    prefix_unknown: bool = False
    response_type: str | None = None
    response_evidence: str | None = None
    body_type: str | None = None
    body_keys: list[str] | None = None
    body_evidence: str | None = None
    function: str | None = None
    reads_json: bool = False


@dataclass
class FuncSpan:
    name: str
    start: int
    body_start: int
    end: int
    params: dict[str, str]
    return_type: str | None


FRONTEND_GLOBS = ("*.ts", "*.tsx", "*.mts", "*.cts", "*.js", "*.jsx", "*.mjs", "*.cjs", "*.vue", "*.svelte")
_SKIP_FILE = re.compile(r"\.(test|spec|stories|e2e|cy)\.\w+$|\.d\.[mc]?ts$|\.min\.js$|(^|[./])config\.[mc]?[jt]s$")


def script_blocks_only(src: str) -> str:
    """Keep only the <script> contents of a .vue/.svelte file. Everything else becomes
    spaces (newlines kept), so offsets and line numbers still match the original file."""
    keep = [False] * len(src)
    for m in re.finditer(r"<script\b[^>]*>(.*?)</script\s*>", src, re.S | re.I):
        for k in range(m.start(1), m.end(1)):
            keep[k] = True
    return "".join(c if keep[k] or c == "\n" else " " for k, c in enumerate(src))


class TsFile:
    def __init__(self, path: Path, root: Path):
        self.path = path
        self.rel = str(path.relative_to(root)).replace("\\", "/")
        self.src = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix in (".vue", ".svelte"):
            self.src = script_blocks_only(self.src)
        self.nc, self.fm = mask_ts(self.src)
        self.decls: list[TsDecl] = []
        self.consts: dict[str, str] = {}
        self.funcs: list[FuncSpan] = []
        self._decls()
        self._consts()
        self._funcs()

    def line_of(self, i: int) -> int:
        return self.src.count("\n", 0, i) + 1

    def _decls(self) -> None:
        for m in re.finditer(r"\binterface\s+(" + IDENT + r")\s*(<[^{]*?>)?\s*(?:extends\s+([^{]+))?\{", self.fm):
            ob = m.end() - 1
            cb = match_close(self.fm, ob)
            members = parse_members(self.nc[ob + 1:cb], ob + 1, self.src)
            ext = [e.strip().split("<")[0] for e in split_top(m.group(3) or "", ",") if e.strip()]
            self.decls.append(TsDecl(m.group(1), self.rel, self.line_of(m.start()), members, extends=ext))
        for m in re.finditer(r"\btype\s+(" + IDENT + r")\s*(<[^=]*?>)?\s*=\s*", self.fm):
            j = m.end()
            # alias body ends at the first ';' (or blank line) outside brackets
            depth, k = 0, j
            while k < len(self.fm):
                ch = self.fm[k]
                if ch in "({[<":
                    depth += 1
                elif ch in ")}]>" and not (ch == ">" and self.fm[k - 1] == "="):
                    depth -= 1
                elif depth == 0 and (ch == ";" or self.fm.startswith("\n\n", k) or
                                     (ch == "\n" and re.match(r"\s*(export|const|let|function|interface|type|import|async)\b", self.fm[k:]))):
                    break
                k += 1
            text = self.nc[j:k].strip()
            line = self.line_of(m.start())
            if text.startswith("{") and match_close(text, 0) == len(text) - 1:
                ob = j + self.nc[j:].index("{")
                members = parse_members(self.nc[ob + 1:match_close(self.fm, ob)], ob + 1, self.src)
                self.decls.append(TsDecl(m.group(1), self.rel, line, members))
            else:
                self.decls.append(TsDecl(m.group(1), self.rel, line, None, alias_text=text))

    def _consts(self) -> None:
        # module/function constants, and class fields (`private api = '/api/orders'`, used as this.api)
        decl = r"(?:\b(?:const|let|var)\s+|^[ \t]*(?:(?:private|public|protected|readonly|static)\s+)+)"
        for m in re.finditer(decl + r"(" + IDENT + r")\s*(?::\s*string\s*)?=\s*(['\"`])", self.nc, re.M):
            q = m.group(2)
            start = m.end()
            end = self.nc.find(q, start) if q != "`" else self._template_end(start)
            if end > start - 1:
                self.consts[m.group(1)] = q + self.nc[start:end] + q
        for m in re.finditer(r"\b(?:const|let|var)\s+(" + IDENT + r")\s*=\s*axios\.create\(\s*\{", self.nc):
            ob = m.end() - 1
            body = self.nc[ob:match_close(self.fm, ob) + 1]
            bm = re.search(r"baseURL\s*:\s*(['\"`])(.*?)\1", body)
            self.consts[f"__axios__{m.group(1)}"] = bm.group(2) if bm else ""

    def _template_end(self, i: int) -> int:
        depth = 0
        while i < len(self.nc):
            if self.nc.startswith("${", i):
                depth += 1
                i += 2
                continue
            if self.nc[i] == "}" and depth:
                depth -= 1
            elif self.nc[i] == "`" and not depth:
                return i
            i += 1
        return i

    def _funcs(self) -> None:
        pats = [
            r"\bfunction\s*\*?\s*(" + IDENT + r")\s*(<[^(]*?>)?\s*\(",
            r"\b(?:const|let|var)\s+(" + IDENT + r")\s*(?::[^=]+)?=\s*(?:async\s*)?(?:<[^(]*?>)?\s*\(",
            r"(?:^|[,{]\s*)(?:async\s+)?(" + IDENT + r")\s*(?::\s*(?:async\s*)?|\s*)\(",
            r"\b(" + IDENT + r")\s*:\s*(?:async\s*)?(?:function\s*)?\(",
        ]
        seen = set()
        for pat in pats:
            for m in re.finditer(pat, self.fm, re.M):
                po = m.end() - 1
                if po in seen:
                    continue
                pc = match_close(self.fm, po)
                k = pc + 1
                while k < len(self.fm) and self.fm[k].isspace():
                    k += 1
                ret = None
                if k < len(self.fm) and self.fm[k] == ":":
                    r0 = k + 1
                    depth = 0
                    while k < len(self.fm):
                        ch = self.fm[k]
                        if ch in "(<[":
                            depth += 1
                        elif ch in ")>]" and not (ch == ">" and self.fm[k - 1] == "="):
                            depth -= 1
                        elif depth == 0 and (ch == "{" or self.fm.startswith("=>", k)):
                            break
                        k += 1
                    ret = self.nc[r0:k].strip()
                if self.fm.startswith("=>", k):
                    k += 2
                    while k < len(self.fm) and self.fm[k].isspace():
                        k += 1
                if k >= len(self.fm):
                    continue
                if self.fm[k] == "{":
                    end = match_close(self.fm, k)
                else:  # expression body or non-function (call expression) -> bounded scan
                    if self.fm[k] in ";,)":
                        continue
                    depth, e = 0, k
                    while e < len(self.fm):
                        ch = self.fm[e]
                        if ch in "({[":
                            depth += 1
                        elif ch in ")}]":
                            if depth == 0:
                                break
                            depth -= 1
                        elif depth == 0 and ch in ";,":
                            break
                        e += 1
                    end = e
                name = m.group(1)
                if name in ("if", "for", "while", "switch", "catch", "return", "function", "fetch") or name in HTTP_VERBS:
                    continue
                seen.add(po)
                params = {}
                for prm in split_top(self.nc[po + 1:pc], ","):
                    pm = re.match(r"\s*(?:\.\.\.)?(" + IDENT + r")\??\s*:\s*(.+?)\s*(?:=.*)?$", prm, re.S)
                    if pm:
                        params[pm.group(1)] = pm.group(2).strip()
                self.funcs.append(FuncSpan(name, m.start(), k, end, params, ret))

    def enclosing(self, i: int) -> FuncSpan | None:
        best = None
        for f in self.funcs:
            if f.body_start <= i <= f.end and (best is None or f.body_start > best.body_start):
                best = f
        return best


class TsProject:
    def __init__(self, root: Path, exclude: list[str], extra_clients: dict[str, str]):
        self.root = root
        self.files: list[TsFile] = []
        skip_dirs = {"node_modules", "dist", "build", ".next", ".nuxt", ".svelte-kit", "coverage", "out", ".git",
                     "public", "vendor", "__tests__", "__mocks__", "e2e", "cypress"}
        paths = {p for g in FRONTEND_GLOBS for p in root.rglob(g)}
        for p in sorted(paths):
            rel = p.relative_to(root)
            rel_s = str(rel).replace("\\", "/")
            if set(rel.parts) & skip_dirs or _SKIP_FILE.search(p.name):
                continue
            if any(rel_s.startswith(e.strip("/")) or re.search(e, rel_s) for e in exclude if e):
                continue
            try:
                self.files.append(TsFile(p, root))
            except Exception:
                continue
        self.decls: dict[str, list[TsDecl]] = {}
        for f in self.files:
            for d in f.decls:
                self.decls.setdefault(d.name, []).append(d)
        self.global_consts: dict[str, str] = {}
        counts: dict[str, int] = {}
        for f in self.files:
            for k, v in f.consts.items():
                counts[k] = counts.get(k, 0) + 1
                self.global_consts[k] = v
        self.global_consts = {k: v for k, v in self.global_consts.items() if counts[k] == 1 or k.startswith("__axios__")}
        self.axios_instances = {k[len("__axios__"):]: v for k, v in self.global_consts.items() if k.startswith("__axios__")}
        self.extra_clients = extra_clients
        self.calls: list[CallSite] = []
        for f in self.files:
            self._calls(f)

    def decl(self, name: str, prefer_file: str | None = None) -> TsDecl | None:
        ds = self.decls.get(name) or []
        if not ds:
            return None
        if prefer_file:
            for d in ds:
                if d.file == prefer_file:
                    return d
        return ds[0]

    def members_of(self, d: TsDecl, depth: int = 0) -> list[TsMember] | None:
        if d.members is None:
            if d.alias_text:
                c = classify(d.alias_text)
                if c["kind"] == "object":
                    return c["members"]
                if c["kind"] == "intersection":
                    out = []
                    for part in c["parts"]:
                        if part["kind"] == "object":
                            out += part["members"]
                        elif part["kind"] == "ref" and depth < 5 and (sub := self.decl(part["name"], d.file)):
                            out += self.members_of(sub, depth + 1) or []
                    return out
                if c["kind"] == "ref" and depth < 5 and (sub := self.decl(c["name"], d.file)):
                    return self.members_of(sub, depth + 1)
            return None
        out = list(d.members)
        for e in d.extends:
            if depth < 5 and (sub := self.decl(e, d.file)):
                have = {m.name for m in out}
                out += [m for m in (self.members_of(sub, depth + 1) or []) if m.name not in have]
        return out

    # ------------------------------------------------------------------ calls
    def _resolve_expr(self, f: TsFile, expr: str) -> tuple[str | None, bool]:
        """Expression -> URL string with PLACEHOLDERs, and whether it was resolved at all."""
        expr = expr.strip()
        expr = re.sub(r"\s+as\s+const$", "", expr)
        expr = re.sub(r"^this\.(?=" + IDENT + r"$)", "", expr)  # this.apiUrl -> class field apiUrl
        if not expr:
            return None, False
        parts = split_top(expr, "+")
        if len(parts) > 1:
            out = ""
            for p in parts:
                s, ok = self._resolve_expr(f, p)
                out += s if ok and s is not None else PLACEHOLDER
            return out, True
        if expr[0] in "'\"" and expr[-1] == expr[0]:
            return expr[1:-1], True
        if expr[0] == "`" and expr[-1] == "`":
            body = expr[1:-1]
            out, i = "", 0
            while i < len(body):
                if body.startswith("${", i):
                    depth, j = 1, i + 2
                    while j < len(body) and depth:
                        depth += {"{": 1, "}": -1}.get(body[j], 0)
                        j += 1
                    inner = re.sub(r"^this\.", "", body[i + 2:j - 1].strip())
                    if re.fullmatch(IDENT, inner) and inner in (f.consts | self.global_consts):
                        s, ok = self._resolve_expr(f, (f.consts.get(inner) or self.global_consts[inner]))
                        out += s if ok and s is not None else PLACEHOLDER
                    else:
                        out += PLACEHOLDER
                    i = j
                else:
                    out += body[i]
                    i += 1
            return out, True
        if re.fullmatch(IDENT, expr):
            v = f.consts.get(expr) or self.global_consts.get(expr)
            if v:
                return self._resolve_expr(f, v)
        return None, False

    def _calls(self, f: TsFile) -> None:
        fm, nc = f.fm, f.nc
        verbs = "|".join(HTTP_VERBS + ("request",))
        instances = set(self.axios_instances) | {"axios"}
        pat = re.compile(
            r"(?<![\w$.])(fetch|" + "|".join(map(re.escape, self.extra_clients)) + r")\s*(<)?(?=[<(])"
            if self.extra_clients else r"(?<![\w$.])(fetch)\s*(?=\()"
        )
        for m in pat.finditer(fm):
            i = m.end()
            generic = None
            if i < len(fm) and fm[i] == "<":
                gc = match_close(fm, i)
                generic = nc[i + 1:gc].strip()
                i = gc + 1
            while i < len(fm) and fm[i].isspace():
                i += 1
            if i >= len(fm) or fm[i] != "(":
                continue
            name = m.group(1)
            base = self.extra_clients.get(name, "") if name != "fetch" else ""
            self._add_call(f, m.start(), i, name, base, None, generic)
        # Angular: fields typed HttpClient (constructor injection) or set from inject(HttpClient)
        ng = set()
        if "HttpClient" in nc:
            ng = set(re.findall(r"(" + IDENT + r")\s*:\s*HttpClient\b", nc)) | \
                set(re.findall(r"(" + IDENT + r")\s*=\s*inject\s*\(\s*HttpClient\s*\)", nc))
        for m in re.finditer(r"(?<![\w$])(" + IDENT + r")\s*\.\s*(" + verbs + r")\s*(?=[<(])", fm):
            inst, verb = m.group(1), m.group(2)
            angular = inst in ng and inst not in instances
            if not angular and inst not in instances:
                continue
            if angular and verb == "request":
                continue  # HttpClient.request(method, url, ...) is rare; not modelled
            i = m.end()
            generic = None
            if fm[i] == "<":
                gc = match_close(fm, i)
                generic = nc[i + 1:gc].strip()
                i = gc + 1
            while i < len(fm) and fm[i].isspace():
                i += 1
            if fm[i] != "(":
                continue
            if angular:
                self._add_call(f, m.start(), i, f"angular:{inst}", "", verb.upper(), generic)
                continue
            base = self.axios_instances.get(inst, "")
            self._add_call(f, m.start(), i, f"axios:{inst}", base, verb.upper() if verb != "request" else None, generic)

    def _add_call(self, f: TsFile, start: int, paren: int, client: str, base: str, method: str | None, generic: str | None):
        fm, nc = f.fm, f.nc
        close = match_close(fm, paren)
        args = split_top(nc[paren + 1:close], ",")
        if not args:
            return
        url_expr = args[0].strip()
        opts = args[1] if len(args) > 1 else ""
        lib_style = client.startswith(("axios:", "angular:"))  # method from the verb, body as 2nd argument
        if not lib_style:
            mm = re.search(r"\bmethod\s*:\s*(['\"`])(\w+)\1", opts)
            if mm:
                method = mm.group(2).upper()
            elif re.search(r"\bmethod\s*[:,}]", opts) or (opts.strip() and re.fullmatch(IDENT, opts.strip())):
                method = None  # dynamic / options object built elsewhere
            else:
                method = "GET"
        elif method is None:  # axios.request({ url, method })
            mm = re.search(r"\bmethod\s*:\s*(['\"`])(\w+)\1", url_expr)
            um = re.search(r"\burl\s*:\s*([^,}]+)", url_expr)
            method = mm.group(2).upper() if mm else None
            url_expr = um.group(1) if um else url_expr
        url, ok = self._resolve_expr(f, url_expr)
        cs = CallSite(f.rel, f.line_of(start), client, method, url_expr[:120], None)
        if ok and url is not None:
            cs.path, cs.prefix_unknown = normalize_url(url, base)
        fn = f.enclosing(start)
        if fn:
            cs.function = fn.name
        # ---- response type evidence
        seg_end = fn.end if fn else min(len(nc), close + 600)
        nxt = re.search(r"(?<![\w$.])(fetch|" + "|".join(map(re.escape, self.axios_instances | {"axios": ""})) + r")\s*[.(<]", fm[close:seg_end])
        window_end = close + nxt.start() if nxt else seg_end
        window = _blank_error_paths(nc[close:window_end], fm[close:window_end])
        cs.reads_json = ".json()" in window
        if client.startswith("angular:"):
            # HttpClient parses the body as JSON unless the options say responseType: 'text' / 'blob' / ...
            opt_text = args[2] if method in ("POST", "PUT", "PATCH") and len(args) > 2 else opts
            cs.reads_json = not re.search(r"responseType\s*:\s*['\"](text|blob|arraybuffer)['\"]", opt_text or "")
        if generic:
            cs.response_type, cs.response_evidence = generic, "generic"
        else:
            cm = re.search(r"\.json\(\)\s*\)?\s*as\s+", window) or re.search(r"\.data\s*\)?\s*as\s+", window)
            if cm:
                cs.response_type, cs.response_evidence = _read_type(window, cm.end()), "cast"
            else:
                vm = re.search(r"(?:const|let)\s+\w+\s*:\s*", window)
                if vm and re.match(r"[^=]+=\s*await\s+[\w.]+\.json\(\)", window[vm.start():]):
                    cs.response_type, cs.response_evidence = _read_type(window, vm.end()), "annotation"
                elif fn and fn.return_type and re.search(r"return\s+(?:\(?\s*await\s+)?[\w.]+\.json\(\)|return\s+[\w.()\s]*\.data\s*;?", window):
                    rt = fn.return_type
                    pm = re.fullmatch(r"Promise\s*<(.*)>", rt, re.S)
                    cs.response_type, cs.response_evidence = (pm.group(1).strip() if pm else rt), "return type"
        # ---- body evidence
        body_expr = None
        if not lib_style:
            bm = re.search(r"\bbody\s*:\s*JSON\.stringify\s*\(", opts)
            if bm:
                o = bm.end() - 1
                _, ofm = mask_ts(opts)
                body_expr = opts[o + 1:match_close(ofm, o)].strip()
                cs.body_evidence = "opaque"  # refined below when the expression can be typed
            elif re.search(r"\bbody\s*:\s*(\w*[Ff]orm\w*)", opts):
                cs.body_evidence = "multipart"
            elif re.search(r"\bbody\s*[:,}]", opts):
                cs.body_evidence = "opaque"
        elif method in ("POST", "PUT", "PATCH") and len(args) > 1:
            body_expr = args[1].strip()
        if body_expr:
            if body_expr.startswith("{"):
                inner = body_expr[1:match_close(mask_ts(body_expr)[1], 0)]
                keys = []
                for part in split_top(inner, ","):
                    km = re.match(r"\s*(?:['\"]?)([\w$]+)(?:['\"]?)\s*(?::|$)", part)
                    if part.strip().startswith("..."):
                        sp = part.strip()[3:].strip()
                        if fn and sp in fn.params:
                            cs.body_type = fn.params[sp]
                        continue
                    if km:
                        keys.append(km.group(1))
                cs.body_keys = keys
                cs.body_evidence = "object literal"
            elif re.fullmatch(IDENT, body_expr):
                t = fn.params.get(body_expr) if fn else None
                if not t:
                    lm = re.search(r"(?:const|let)\s+" + re.escape(body_expr) + r"\s*:\s*", nc[fn.body_start if fn else 0:start])
                    if lm:
                        t = _read_type(nc[fn.body_start if fn else 0:start], lm.end())
                if t:
                    cs.body_type, cs.body_evidence = t, "parameter type"
        self.calls.append(cs)


def _blank_error_paths(window: str, window_fm: str) -> str:
    """Hide `if (!res.ok) {...}` and catch blocks: casts there describe the error body, not the response."""
    w = list(window)
    for em in re.finditer(r"if\s*\(\s*!\s*[\w.]+\.ok\s*\)\s*\{|if\s*\(\s*[\w.]+\.status\s*>=?\s*[45]\d\d\s*\)\s*\{|"
                          r"\bcatch\s*(?:\([^)]*\))?\s*\{|\.catch\s*\(", window_fm):
        o = em.end() - 1
        e = match_close(window_fm, o)
        for k in range(o, e + 1):
            if w[k] != "\n":
                w[k] = " "
    return "".join(w)


def _read_type(text: str, i: int) -> str:
    """Read a TS type expression starting at text[i] (stops at ; ) , = or newline at depth 0)."""
    depth, j = 0, i
    while j < len(text):
        ch = text[j]
        if ch in "({[<":
            depth += 1
        elif ch in ")}]>" and not (ch == ">" and text[j - 1] == "="):
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and (ch in ";,=" or (ch == "\n" and not re.match(r"\s*[|&]", text[j + 1:]))):
            break
        elif depth == 0 and text.startswith(").", j):
            break
        j += 1
    return text[i:j].strip().rstrip(".")


def normalize_url(url: str, base: str = "") -> tuple[str | None, bool]:
    """'/api/customers/\\0?x=1' -> '/api/customers/{}'. Returns (path, prefix_unknown)."""
    u = url.strip()
    u = re.sub(r"^https?://[^/]+", "", u)
    if base and not u.startswith("/") and not re.match(r"https?://", u):
        u = base.rstrip("/") + "/" + u
    elif base and u.startswith("/") and not u.startswith(base.rstrip("/") + "/") and base.startswith("/"):
        u = base.rstrip("/") + u
    elif base and re.match(r"https?://", base):
        u = re.sub(r"^https?://[^/]+", "", base).rstrip("/") + "/" + u.lstrip("/")
    u = u.split("?")[0].split("#")[0]
    prefix_unknown = False
    if u.startswith(PLACEHOLDER):
        prefix_unknown = True
        u = u.lstrip(PLACEHOLDER)
    segs = []
    raw_segs = [s for s in u.split("/") if s != ""]
    for idx, s in enumerate(raw_segs):
        if s == PLACEHOLDER * len(s):
            segs.append("{}")
        elif PLACEHOLDER in s:
            if idx == len(raw_segs) - 1 and s.endswith(PLACEHOLDER) and not s.startswith(PLACEHOLDER):
                segs.append(s.rstrip(PLACEHOLDER))  # `payments${query}` -> trailing query string
            else:
                segs.append("{}")
        else:
            segs.append(s)
    if not segs and not u.startswith("/"):
        return None, prefix_unknown
    return "/" + "/".join(segs), prefix_unknown
