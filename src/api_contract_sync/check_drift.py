#!/usr/bin/env python3
"""Detect drift between a Spring backend contract and a TypeScript frontend.

Usage:
    python check_drift.py <backend-dir | openapi.json | contract.json> <frontend-src-dir>
        [--md report.md] [--json report.json]
        [--strict-nulls] [--client-fn apiFetch[:/api]] [--exclude src/api/generated]
        [--fail-on error|warning|never] [--github-annotations] [--show-info]

What it checks
  endpoints   every fetch/axios call resolves to a backend method+path
  responses   the TS type a response is cast to matches what Jackson sends
  bodies      the TS type / object literal sent matches what the backend reads
  enums       TS literal unions vs Java enum constants
  by name     TS interfaces whose name equals a backend DTO/entity name

Exit code 1 when any error-level finding exists (use in CI); --fail-on changes the
threshold. A Spring backend directory is extracted on the fly; any other backend
(FastAPI, NestJS, .NET, Go, ...) is checked through its OpenAPI/Swagger document.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

try:  # inside the api_contract_sync package
    from .ts_parser import TsProject, CallSite, TsMember, classify
except ImportError:  # run as a standalone script (the Claude skill, or copied into a repo)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ts_parser import TsProject, CallSite, TsMember, classify  # noqa: E402

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
DOWNGRADE = {"error": "warning", "warning": "info", "info": "info"}


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    frontend: str | None = None  # file:line
    backend: str | None = None  # file:line
    via: list[str] = field(default_factory=list)
    hint: str | None = None

    def key(self):
        return (self.code, self.message, self.frontend, self.backend)


def be_type_str(t: dict) -> str:
    k = t.get("kind")
    if k == "ref":
        return t["name"]
    if k == "array":
        return be_type_str(t["items"]) + "[]"
    if k == "map":
        return f"Record<string, {be_type_str(t['values'])}>"
    if k == "page":
        return f"Page<{be_type_str(t['items'])}>"
    return k + (f" ({t['format']})" if t.get("format") else "")


def path_key(p: str) -> list[str]:
    return [("{}" if s.startswith("{") else s) for s in p.strip("/").split("/") if s]


class Checker:
    def __init__(self, contract: dict, fe: TsProject, strict_nulls: bool):
        self.c = contract
        self.types = contract["types"]
        self.fe = fe
        self.strict_nulls = strict_nulls
        self.findings: dict[tuple, Finding] = {}
        self.hidden_nulls = 0
        self.matched_eps: set[int] = set()
        self.compared_decls: set[tuple[str, str]] = set()
        self.backend_root = contract.get("javaRoot", "")
        self.eps = contract["endpoints"]

    # ----------------------------------------------------------- reporting
    def add(self, sev: str, code: str, msg: str, fe: str | None = None, be: str | None = None,
            via: str | None = None, hint: str | None = None, weak: bool = False) -> None:
        if weak:
            sev = DOWNGRADE[sev]
        # `Product[].sku` (list endpoint) and `Product.sku` (single) point at the same TS
        # line and need the same fix: report them once, with both endpoints under `via`.
        msg = re.sub(r"\[\]\.", ".", msg)
        f = Finding(sev, code, msg, fe, be, [], hint)
        k = f.key()
        if k in self.findings:
            ex = self.findings[k]
            if SEVERITY_ORDER[sev] < SEVERITY_ORDER[ex.severity]:
                ex.severity = sev
            f = ex
        else:
            self.findings[k] = f
        if via and via not in f.via:
            f.via.append(via)

    # ----------------------------------------------------------- endpoints
    def match_endpoint(self, cs: CallSite):
        fk = path_key(cs.path)
        best, best_score = [], -1
        for idx, ep in enumerate(self.eps):
            bk = path_key(ep["path"])
            if cs.prefix_unknown:
                if len(bk) < len(fk):
                    continue
                bk = bk[len(bk) - len(fk):]
            if len(bk) != len(fk):
                continue
            score = 0
            for a, b in zip(fk, bk):
                if a == b:
                    score += 3
                elif b == "{}":
                    score += 1  # backend variable accepts a literal segment
                elif a == "{}":
                    score += 0  # dynamic frontend segment, backend literal: possible
                else:
                    score = -1
                    break
            if score < 0:
                continue
            if score > best_score:
                best, best_score = [idx], score
            elif score == best_score:
                best.append(idx)
        return best

    def check_calls(self) -> None:
        for cs in self.fe.calls:
            loc = f"{cs.file}:{cs.line}"
            if cs.path is None:
                self.add("info", "unresolved-call", f"Could not resolve the URL `{cs.raw_url}` ({cs.client}); check by hand", loc)
                continue
            if not cs.path.startswith("/") or cs.path == "/":
                continue
            cands = self.match_endpoint(cs)
            if not cands:
                close = self.closest(cs.path)
                self.add("error", "endpoint-missing", f"{cs.method or '?'} {cs.path} has no backend endpoint", loc,
                         hint=f"closest backend paths: {', '.join(close)}" if close else None)
                continue
            if cs.method:
                same = [i for i in cands if self.eps[i]["method"] == cs.method]
            else:
                same = cands
            if not same:
                methods = sorted({self.eps[i]["method"] for i in cands})
                ep0 = self.eps[cands[0]]
                self.matched_eps.update(cands)  # it is called, just with the wrong verb
                self.add("error", "method-mismatch",
                         f"{cs.method} {cs.path}: backend only accepts {', '.join(methods)} on {ep0['path']}",
                         loc, self.be_loc(ep0["source"]))
                continue
            for i in same:
                self.matched_eps.add(i)
            ep = self.eps[same[0]]
            via = f"{ep['method']} {ep['path']}"
            self.check_response(cs, ep, loc, via)
            self.check_body(cs, ep, loc, via)

    def closest(self, path: str) -> list[str]:
        fk = path_key(path)
        scored = []
        for ep in self.eps:
            bk = path_key(ep["path"])
            common = sum(1 for a, b in zip(fk, bk) if a == b or "{}" in (a, b))
            tail = 2 if fk and bk and fk[-1] == bk[-1] else 0
            scored.append((common + tail - abs(len(fk) - len(bk)), f"{ep['method']} {ep['path']}"))
        scored.sort(key=lambda x: -x[0])
        return [s for sc, s in scored[:3] if sc > 1]

    def be_loc(self, src: str | None) -> str | None:
        return src.replace("\\", "/") if src else None

    def check_response(self, cs: CallSite, ep: dict, loc: str, via: str) -> None:
        resp = ep["response"]
        fmt = resp["format"]
        if fmt == "text" and (cs.reads_json or cs.response_evidence == "cast"):
            self.add("error", "text-as-json",
                     f"{via} returns plain text (text/plain) but the frontend parses it as JSON", loc,
                     self.be_loc(ep["source"]), via,
                     hint="call response.text(), or return a JSON object (in Spring: a record/Map instead of a bare String)")
            return
        if not cs.response_type:
            return
        if fmt == "none":
            fe_t = classify(cs.response_type)
            if fe_t["kind"] not in ("unknown", "null") and cs.response_evidence in ("cast", "generic"):
                self.add("error", "no-response-body",
                         f"{via} returns no body (void / 204), but the frontend expects `{cs.response_type}`",
                         loc, self.be_loc(ep["source"]), via)
            return
        weak = cs.response_evidence == "return type"
        self.compare(classify(cs.response_type), resp["type"], "read", self.label(cs.response_type, cs, "response"),
                     loc, ep["source"], via, cs.file, weak=weak)

    @staticmethod
    def label(type_text: str, cs: CallSite, role: str) -> str:
        """Short name for a TS type in messages; inline object types get named after their function."""
        t = type_text.strip()
        if len(t) <= 40 and "\n" not in t:
            return t
        return f"{cs.function or 'call'}() {role}"

    def check_body(self, cs: CallSite, ep: dict, loc: str, via: str) -> None:
        body = ep.get("body")
        sent = cs.body_type or cs.body_keys is not None
        if sent and not body and cs.body_evidence != "multipart":
            self.add("warning", "body-ignored", f"{via} takes no request body (no @RequestBody); the JSON body sent here is ignored",
                     loc, self.be_loc(ep["source"]), via)
            return
        if body and body["required"] and not sent and cs.body_evidence != "multipart" and cs.method in ("POST", "PUT", "PATCH"):
            if cs.client == "fetch" and cs.body_evidence is None:
                self.add("warning", "body-missing", f"{via} requires a JSON request body but none is sent here",
                         loc, self.be_loc(ep["source"]), via)
            return
        if not body:
            return
        if cs.body_type:
            self.compare(classify(cs.body_type), body["type"], "write", self.label(cs.body_type, cs, "body"),
                         loc, ep["source"], via, cs.file)
        elif cs.body_keys is not None:
            members = [TsMember(k, "unknown", False, cs.line) for k in cs.body_keys]
            self.compare({"kind": "object", "members": members, "nullable": False}, body["type"], "write",
                         self.label("{ " + ", ".join(cs.body_keys) + " }", cs, "body"), loc, ep["source"], via, cs.file)

    # ----------------------------------------------------------- types
    def compare(self, fe: dict, be: dict, view: str, fe_label: str, fe_loc: str, be_loc: str | None, via: str,
                fe_file: str, path: str = "", depth: int = 0, seen: set | None = None, weak: bool = False) -> None:
        seen = seen if seen is not None else set()
        if depth > 6:
            return
        bk, fk = be.get("kind"), fe.get("kind")
        where = path or fe_label
        be_loc = self.be_loc(be_loc)
        if fk in ("unknown", "null") or bk in ("unknown", "typeParam"):
            return
        if fk == "union":
            for opt in fe["options"]:
                if self._kind_ok(opt, be):
                    return self.compare(opt, be, view, fe_label, fe_loc, be_loc, via, fe_file, path, depth, seen, weak)
            fk = fe["options"][0]["kind"]
        if fk == "intersection":
            members = []
            for part in fe["parts"]:
                m = self._fe_members(part, fe_file)
                if m:
                    members += m
            if members:
                return self.compare({"kind": "object", "members": members, "nullable": fe.get("nullable")}, be, view,
                                    fe_label, fe_loc, be_loc, via, fe_file, path, depth, seen, weak)
            return
        if bk == "ref":
            td = self.types.get(be["name"])
            if not td:
                return
            if td["kind"] == "enum":
                return self.compare_enum(fe, td, be["name"], view, where, fe_loc, via, fe_file, weak)
            if fk == "string" and td["kind"] == "object":
                self.add("error", "type-mismatch", f"`{where}` is `string` in TS but the backend sends object {be['name']}",
                         fe_loc, td.get("source"), via, weak=weak)
                return
            if fk not in ("ref", "object", "map"):
                if fk in ("array",):
                    self.add("error", "type-mismatch", f"`{where}` is an array in TS but the backend sends a single {be['name']}",
                             fe_loc, be_loc, via, weak=weak)
                elif fk in ("number", "boolean"):
                    self.add("error", "type-mismatch", f"`{where}` is `{fk}` in TS but the backend sends object {be['name']}",
                             fe_loc, be_loc, via, weak=weak)
                return
            if fk == "map":
                return
            fe_members, fe_decl_loc, partial = self._resolve_fe_object(fe, fe_file)
            if fe_members is None:
                return
            key = (fe_decl_loc or fe_label, be["name"], view)
            if key in seen:
                return
            seen = seen | {key}
            if fe_decl_loc and fe.get("kind") == "ref":
                self.compared_decls.add((fe["name"], fe_decl_loc.split(":")[0]))
            return self.compare_object(fe_members, td, be["name"], view, fe_decl_loc or fe_loc, via, fe_file,
                                       path or fe_label, depth, seen, weak, partial or bool(fe.get("omit") or fe.get("pick")))
        if bk == "page":
            if fk == "array":
                self.add("error", "page-vs-array", f"`{where}` is an array in TS but the backend returns a Spring Page "
                                                   f"(items are under `.content`)", fe_loc, be_loc, via, weak=weak)
            return
        if bk == "array":
            if fk != "array":
                self.add("error", "type-mismatch", f"`{where}` is `{fk if fk != 'ref' else fe.get('name')}` in TS but the backend sends an array ({be_type_str(be)})",
                         fe_loc, be_loc, via, weak=weak)
                return
            item_path = (path + "[]") if path else (fe_label if fe_label.endswith("[]") else fe_label + "[]")
            return self.compare(fe["items"], be["items"], view, fe_label, fe_loc, be_loc, via, fe_file,
                                item_path, depth + 1, seen, weak)
        if bk == "map":
            if fk in ("array", "string", "number", "boolean"):
                self.add("error", "type-mismatch", f"`{where}` is `{fk}` in TS but the backend sends a map/object",
                         fe_loc, be_loc, via, weak=weak)
            return
        if not self._kind_ok(fe, be):
            fe_desc = fe.get("name") if fk == "ref" else fk
            hint = None
            if be.get("format") == "decimal" and fk == "string":
                hint = ("BigDecimal is serialized as a JSON number by default. If Jackson is configured with "
                        "WRITE_BIGDECIMAL_AS_STRING, re-run extract_spring.py with --bigdecimal string")
            elif fk == "date":
                hint = "JSON has no Date type; the value arrives as an ISO string. Type it as string and parse explicitly"
            elif be.get("kind") == "string" and fk == "number" and be.get("format") in ("date", "date-time"):
                hint = "Java dates are serialized as ISO strings unless WRITE_DATES_AS_TIMESTAMPS is enabled"
            sev = "error"
            if view == "write" and {fk, bk} <= {"string", "number", "boolean"}:
                # Jackson coerces "12.5" -> 12.5 (and back) on input by default, so the request still works.
                sev = "warning"
                hint = "Jackson coerces scalar strings/numbers on input, so this works today, but the TS type misdescribes the API"
            self.add(sev, "type-mismatch", f"`{where}` is `{fe_desc}` in TS but `{be_type_str(be)}` in the backend",
                     fe_loc, be_loc, via, hint, weak=weak)

    def _kind_ok(self, fe: dict, be: dict) -> bool:
        fk, bk = fe.get("kind"), be.get("kind")
        if fk in ("unknown", "null", "union", "intersection") or bk in ("unknown", "typeParam"):
            return True
        if bk == "ref":
            td = self.types.get(be["name"], {})
            if td.get("kind") == "enum":
                return fk in ("string", "ref")
            return fk in ("ref", "object", "map")
        if bk == "binary":
            return fk in ("binary", "string", "ref")
        if fk == "ref":
            d = self.fe.decl(fe["name"])
            if d and d.alias_text:
                return self._kind_ok(classify(d.alias_text), be)
            return bk in ("map", "page")
        return fk == bk or (bk == "page" and fk == "object")

    def _fe_members(self, fe: dict, fe_file: str):
        m, _, _ = self._resolve_fe_object(fe, fe_file)
        return m

    def _resolve_fe_object(self, fe: dict, fe_file: str):
        if fe["kind"] == "object":
            return fe["members"], None, bool(fe.get("partial"))
        if fe["kind"] == "ref":
            d = self.fe.decl(fe["name"], fe_file)
            if not d:
                return None, None, False
            members = self.fe.members_of(d)
            if members is None:
                return None, None, False
            if fe.get("omit"):
                members = [m for m in members if m.name not in fe["omit"]]
            if fe.get("pick"):
                members = [m for m in members if m.name in fe["pick"]]
            return members, f"{d.file}:{d.line}", bool(fe.get("partial"))
        return None, None, False

    def compare_object(self, members: list[TsMember], td: dict, be_name: str, view: str, fe_loc: str, via: str,
                       fe_file: str, label: str, depth: int, seen: set, weak: bool, partial: bool) -> None:
        fe_file_only = fe_loc.split(":")[0]
        props = {p["name"]: p for p in td["properties"]}
        visible = {n: p for n, p in props.items() if not (p.get("writeOnly") if view == "read" else p.get("readOnly"))}
        fe_names = {m.name for m in members if m.name != "__index__"}
        has_index = any(m.name == "__index__" for m in members)
        for m in members:
            if m.name == "__index__":
                continue
            mloc = f"{fe_file_only}:{m.line}" if m.line else fe_loc
            p = visible.get(m.name)
            if p is None:
                other = props.get(m.name)
                json_ignored = m.name in td.get("ignored", ())
                if view == "read":
                    if other and other.get("writeOnly"):
                        msg = f"`{label}.{m.name}` is write-only on the backend (never sent in responses)"
                    elif json_ignored:
                        msg = f"`{label}.{m.name}` is @JsonIgnore on backend type {be_name}; it is never sent, so always undefined"
                    else:
                        msg = f"`{label}.{m.name}` does not exist on backend type {be_name}; it is always undefined at runtime"
                    self.add("warning" if m.optional else "error", "field-not-sent", msg, mloc, td.get("source"), via,
                             hint=self._rename_hint(m.name, visible), weak=weak)
                else:
                    if other and other.get("readOnly"):
                        msg = f"`{label}.{m.name}` is read-only on the backend; the value sent is ignored"
                    elif json_ignored:
                        msg = f"`{label}.{m.name}` is @JsonIgnore on backend type {be_name}; the value sent is ignored"
                    else:
                        msg = f"`{label}.{m.name}` is not a field of {be_name}; the backend silently ignores it"
                    self.add("warning", "field-ignored", msg, mloc, td.get("source"), via,
                             hint=self._rename_hint(m.name, visible), weak=weak)
                continue
            be_loc = f"{td['source'].rsplit(':', 1)[0]}:{p['line']}" if p.get("line") else td.get("source")
            if m.type_text != "unknown":
                fe_t = classify(m.type_text)
                self.compare(fe_t, p["type"], view, label, mloc, be_loc, via, fe_file, f"{label}.{m.name}",
                             depth + 1, seen, weak)
                fe_nullable = fe_t.get("nullable") or m.optional
                if view == "read" and p["nullable"] and not fe_nullable:
                    if self.strict_nulls:
                        self.add("warning", "nullability", f"`{label}.{m.name}` can be null from the backend but TS types it as always present",
                                 mloc, be_loc, via, weak=weak)
                    else:
                        self.hidden_nulls += 1
                if view == "write" and not p["nullable"] and fe_nullable and not p.get("generated") \
                        and p.get("nonNullBecause") not in ("primitive", "initialized") and self.strict_nulls:
                    self.add("warning", "nullability", f"`{label}.{m.name}` may be sent as null/omitted but the backend requires it "
                                                       f"({p.get('nonNullBecause')})", mloc, be_loc, via, weak=weak)
        # Only top-level bodies: nested entities are usually references sent as `{ id }` and looked up server-side.
        if view == "write" and not partial and not has_index and depth == 0:
            for n, p in visible.items():
                if n in fe_names or p["nullable"] or p.get("generated") or p.get("identifier"):
                    continue
                why = p.get("nonNullBecause")
                if why == "initialized":
                    continue
                if why == "primitive":
                    zero = "false" if p["type"].get("kind") == "boolean" else "0"
                    self.add("warning" if zero == "false" else "info", "required-field-missing",
                             f"`{label}` never sends `{n}`; {be_name}.{n} is a primitive and silently becomes {zero}",
                             fe_loc, td.get("source"), via, weak=weak)
                else:
                    self.add("warning", "required-field-missing", f"`{label}` never sends `{n}`, which the backend requires ({why})",
                             fe_loc, td.get("source"), via, weak=weak)
        if view == "read":
            missing = [n for n in visible if n not in fe_names]
            if missing and not has_index:
                self.add("info", "field-unused", f"`{label}` omits backend fields of {be_name}: {', '.join(missing)}",
                         fe_loc, td.get("source"), via, weak=weak)

    def _similar(self, name: str, props: dict) -> str | None:
        for p in props.values():
            if p.get("javaName") == name:  # TS used the Java field name, JSON uses another
                return p["name"]
        low = name.lower().replace("_", "")
        for p in props:
            pl = p.lower().replace("_", "")
            if pl == low or pl.rstrip("s") == low.rstrip("s") or (len(low) > 3 and (pl.startswith(low) or low.startswith(pl))):
                return p
        for p in props:  # email -> contactEmail, total -> grandTotal
            pl = p.lower().replace("_", "")
            if len(low) > 3 and (pl.endswith(low) or low.endswith(pl)):
                return p
        return None

    def _rename_hint(self, name: str, props: dict) -> str | None:
        sim = self._similar(name, props)
        if not sim:
            return None
        p = props[sim]
        if p.get("javaName") == name:
            return f"the Java field `{name}` is sent as `{sim}` ({p.get('renamedBy', 'renamed')}); use `{sim}`"
        return f"did you mean `{sim}`?"

    def compare_enum(self, fe: dict, td: dict, name: str, view: str, where: str, fe_loc: str, via: str, fe_file: str, weak: bool):
        lits = fe.get("literals")
        if fe["kind"] == "ref":
            d = self.fe.decl(fe["name"], fe_file)
            if d and d.alias_text:
                c = classify(d.alias_text)
                lits = c.get("literals")
                fe_loc = f"{d.file}:{d.line}"
                self.compared_decls.add((d.name, d.file))
        if not lits:
            return
        be_vals = set(td["values"])
        extra = [v for v in lits if v not in be_vals]
        missing = [v for v in td["values"] if v not in lits]
        if extra:
            self.add("error", "enum-mismatch",
                     f"`{where}` allows {', '.join(map(repr, extra))}, which the backend enum {name} does not have"
                     + (" (requests with it are rejected)" if view == "write" else " (it can never arrive)"),
                     fe_loc, td.get("source"), via, weak=weak)
        if missing and view == "read":
            self.add("warning", "enum-incomplete",
                     f"`{where}` does not handle backend {name} values: {', '.join(missing)}",
                     fe_loc, td.get("source"), via, weak=weak)

    # ----------------------------------------------------------- by name
    def check_by_name(self) -> None:
        for name, td in self.types.items():
            for d in self.fe.decls.get(name, []):
                if (name, d.file) in self.compared_decls:
                    continue
                loc = f"{d.file}:{d.line}"
                if td["kind"] == "enum":
                    if d.alias_text:
                        self.compare_enum(classify(d.alias_text), td, name, "read", name, loc, "same name", d.file, False)
                    continue
                members = self.fe.members_of(d)
                if members is None:
                    continue
                # Name-only evidence is weaker: a TS `Customer` might be a deliberate subset or a different concept.
                self.compare_object(members, td, name, "read", loc, "same name", d.file, name, 0, set(), True, False)

    def unused_endpoints(self) -> list[dict]:
        return [ep for i, ep in enumerate(self.eps) if i not in self.matched_eps]

    def run(self) -> None:
        self.check_calls()
        self.check_by_name()


def render_md(ch: Checker, show_info: bool) -> str:
    fs = sorted(ch.findings.values(), key=lambda f: (SEVERITY_ORDER[f.severity], f.code, f.frontend or ""))
    counts = {s: sum(1 for f in fs if f.severity == s) for s in SEVERITY_ORDER}
    calls = ch.fe.calls
    resolved = sum(1 for c in calls if c.path)
    unused = ch.unused_endpoints()
    out = [
        "# API drift report",
        "",
        f"- Backend: {len(ch.eps)} endpoints, {len(ch.types)} types ({ch.c.get('backend')})",
        f"- Frontend: {len(ch.fe.files)} files, {len(calls)} HTTP call sites ({resolved} resolved), "
        f"{sum(len(v) for v in ch.fe.decls.values())} type declarations",
        f"- Endpoints called by the frontend: {len(ch.matched_eps)} / {len(ch.eps)}",
        f"- **{counts['error']} errors, {counts['warning']} warnings, {counts['info']} info**",
    ]
    if ch.hidden_nulls:
        out.append(f"- {ch.hidden_nulls} nullability differences hidden (re-run with --strict-nulls to list them)")
    for sev, title in (("error", "Errors"), ("warning", "Warnings"), ("info", "Info")):
        group = [f for f in fs if f.severity == sev]
        if not group or (sev == "info" and not show_info):
            continue
        out += ["", f"## {title}", ""]
        for f in group:
            line = f"- **[{f.code}]** {f.message}"
            locs = []
            if f.frontend:
                locs.append(f"Frontend `{f.frontend}`")
            if f.backend:
                locs.append(f"Backend `{f.backend}`")
            if locs:
                line += "  \n  " + " · ".join(locs)
            if f.via:
                shown = f.via[:3]
                line += f"  \n  via {', '.join(shown)}{f' (+{len(f.via) - 3} more)' if len(f.via) > 3 else ''}"
            if f.hint:
                line += f"  \n  _hint: {f.hint}_"
            out.append(line)
    if unused and show_info:
        out += ["", f"## Backend endpoints with no frontend caller ({len(unused)})", ""]
        out += [f"- {e['method']} {e['path']}  (`{e['source']}`)" for e in unused]
    elif unused:
        out += ["", f"_{len(unused)} backend endpoints have no frontend caller and {counts['info']} info items are hidden; "
                    f"use --show-info to list them._"]
    return "\n".join(out) + "\n"


def _gh_escape(s: str, prop: bool = False) -> str:
    s = s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return s.replace(":", "%3A").replace(",", "%2C") if prop else s


def github_annotations(findings: list[Finding], frontend_root: Path) -> list[str]:
    """GitHub Actions workflow commands, so findings show inline on the PR diff."""
    level = {"error": "error", "warning": "warning", "info": "notice"}
    out = []
    for f in sorted(findings, key=lambda f: SEVERITY_ORDER[f.severity]):
        if f.severity == "info":
            continue
        props = [f"title={_gh_escape('API drift: ' + f.code, True)}"]
        if f.frontend:
            file, _, line = f.frontend.rpartition(":")
            path = (frontend_root / file).as_posix() if file else f.frontend
            props[:0] = [f"file={_gh_escape(path, True)}"] + ([f"line={line}"] if line.isdigit() else [])
        msg = f.message + (f" (backend: {f.backend})" if f.backend else "") + (f" Hint: {f.hint}" if f.hint else "")
        out.append(f"::{level[f.severity]} {','.join(props)}::{_gh_escape(msg)}")
    return out


def load_contract(source: Path, bigdecimal=None, context_path=None, naming=None) -> dict:
    """A backend directory, an OpenAPI/Swagger document, or a saved contract JSON."""
    try:
        from .extract_openapi import load_any
    except ImportError:
        from extract_openapi import load_any  # noqa: E402
    return load_any(source, bigdecimal, context_path, naming)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("contract", type=Path,
                    help="Spring backend directory, OpenAPI/Swagger file (any backend language), or a contract JSON")
    ap.add_argument("frontend", type=Path, help="frontend source directory (e.g. frontend/src)")
    ap.add_argument("--md", type=Path, help="write the markdown report here (default: stdout)")
    ap.add_argument("--json", type=Path, help="also write findings as JSON")
    ap.add_argument("--strict-nulls", action="store_true", help="report nullability differences")
    ap.add_argument("--client-fn", action="append", default=[],
                    help="extra fetch-like wrapper, NAME or NAME:BASEURL (repeatable), e.g. apiFetch:/api")
    ap.add_argument("--exclude", action="append", default=[], help="path prefix/regex to skip (repeatable)")
    ap.add_argument("--show-info", action="store_true", help="include info-level findings and unused endpoints")
    ap.add_argument("--fail-on", choices=["error", "warning", "never"], default="error",
                    help="lowest severity that makes the exit code 1 (default: error)")
    ap.add_argument("--no-fail", action="store_true", help="same as --fail-on never")
    ap.add_argument("--github-annotations", action="store_true",
                    help="print GitHub Actions ::error/::warning lines so findings appear on the PR diff")
    ext = ap.add_argument_group("when the first argument is a backend directory (extract on the fly)")
    ext.add_argument("--context-path", default=None)
    ext.add_argument("--bigdecimal", choices=["number", "string"], default=None)
    ext.add_argument("--naming", choices=["camel", "snake", "kebab", "lower", "upper_camel"], default=None)
    a = ap.parse_args(argv)
    if not a.contract.exists():
        ap.error(f"{a.contract} does not exist")
    if not a.frontend.is_dir():
        ap.error(f"{a.frontend} is not a directory")
    contract = load_contract(a.contract, a.bigdecimal, a.context_path, a.naming)
    extra = {}
    for spec in a.client_fn:
        name, _, base = spec.partition(":")
        extra[name] = base
    fe = TsProject(a.frontend, a.exclude, extra)
    ch = Checker(contract, fe, a.strict_nulls)
    ch.run()
    md = render_md(ch, a.show_info)
    if a.md:
        a.md.parent.mkdir(parents=True, exist_ok=True)
        a.md.write_text(md, encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(md)
    fs = list(ch.findings.values())
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps({
            "summary": {s: sum(1 for f in fs if f.severity == s) for s in SEVERITY_ORDER},
            "hiddenNullability": ch.hidden_nulls,
            "findings": [asdict(f) for f in sorted(fs, key=lambda f: SEVERITY_ORDER[f.severity])],
            "unusedEndpoints": [{"method": e["method"], "path": e["path"], "source": e["source"]} for e in ch.unused_endpoints()],
            "unresolvedCalls": [f"{c.file}:{c.line} {c.raw_url}" for c in fe.calls if c.path is None],
        }, indent=2), encoding="utf-8")
    if a.github_annotations:
        for line in github_annotations(fs, a.frontend):
            print(line)
    errors = sum(1 for f in fs if f.severity == "error")
    warnings = sum(1 for f in fs if f.severity == "warning")
    print(f"drift: {errors} errors, {warnings} warnings", file=sys.stderr)
    fail_on = "never" if a.no_fail else a.fail_on
    failing = errors + (warnings if fail_on == "warning" else 0)
    return 1 if failing and fail_on != "never" else 0


if __name__ == "__main__":
    sys.exit(main())
