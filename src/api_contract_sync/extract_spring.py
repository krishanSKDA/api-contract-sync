#!/usr/bin/env python3
"""Extract an HTTP API contract from a Spring Boot (Spring MVC) code base.

Usage:
    python extract_spring.py <backend-dir> [-o contract.json] [--context-path /x]
                             [--bigdecimal number|string] [--naming snake] [--summary]

server.servlet.context-path, spring.jackson.property-naming-strategy and
WRITE_BIGDECIMAL_AS_STRING are read from application.properties/yml when present.

<backend-dir> can be the project root (src/main/java is found automatically)
or any directory of .java files. The contract is a JSON file describing every
endpoint (method, path, params, body, response) and every type reachable from
them, already mapped to JSON / TypeScript-friendly kinds. Both
generate_ts.py and check_drift.py consume it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:  # inside the api_contract_sync package
    from .java_parser import JavaProject, JMethod, JType, TypeRef, find_ann
except ImportError:  # run as a standalone script (the Claude skill, or copied into a repo)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from java_parser import JavaProject, JMethod, JType, TypeRef, find_ann  # noqa: E402

HTTP_MAPPINGS = {
    "GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT",
    "DeleteMapping": "DELETE", "PatchMapping": "PATCH",
}

STRING_TYPES = {"String", "CharSequence", "char", "Character", "UUID", "URI", "URL", "Locale", "Currency", "ZoneId", "Pattern"}
INT_TYPES = {"int", "Integer", "long", "Long", "short", "Short", "byte", "Byte", "BigInteger", "AtomicInteger", "AtomicLong"}
FLOAT_TYPES = {"double", "Double", "float", "Float", "Number"}
BOOL_TYPES = {"boolean", "Boolean", "AtomicBoolean"}
PRIMITIVES = {"int", "long", "short", "byte", "double", "float", "boolean", "char"}
DATE_FORMATS = {
    "LocalDate": "date", "LocalDateTime": "date-time", "OffsetDateTime": "date-time",
    "ZonedDateTime": "date-time", "Instant": "date-time", "Date": "date-time",
    "Timestamp": "date-time", "Calendar": "date-time", "LocalTime": "time",
    "OffsetTime": "time", "Duration": "duration", "Period": "duration", "YearMonth": "year-month", "Year": "year",
}
LIST_TYPES = {"List", "ArrayList", "LinkedList", "Set", "HashSet", "LinkedHashSet", "TreeSet", "SortedSet",
              "Collection", "Iterable", "Stream", "Flux", "Queue", "Deque"}
MAP_TYPES = {"Map", "HashMap", "LinkedHashMap", "TreeMap", "SortedMap", "ConcurrentHashMap", "MultiValueMap", "EnumMap"}
WRAPPERS = {"ResponseEntity", "HttpEntity", "CompletableFuture", "CompletionStage", "Future", "Mono",
            "DeferredResult", "Callable", "WebAsyncTask", "ListenableFuture"}
BINARY_TYPES = {"Resource", "InputStreamResource", "ByteArrayResource", "FileSystemResource", "UrlResource",
                "StreamingResponseBody", "InputStream", "MultipartFile", "Part", "File"}
UNKNOWN_TYPES = {"Object", "JsonNode", "ObjectNode", "ArrayNode", "Serializable", "?"}
# Parameters Spring injects itself; they are not part of the HTTP contract.
FRAMEWORK_PARAMS = {
    "HttpServletRequest", "HttpServletResponse", "ServletRequest", "ServletResponse", "HttpSession",
    "Principal", "Authentication", "Model", "ModelMap", "BindingResult", "Errors", "Locale", "TimeZone",
    "ZoneId", "UriComponentsBuilder", "ServletUriComponentsBuilder", "WebRequest", "NativeWebRequest",
    "ServerWebExchange", "ServerHttpRequest", "ServerHttpResponse", "SessionStatus", "RedirectAttributes",
    "HttpMethod", "InputStream", "OutputStream", "Reader", "Writer", "HttpHeaders", "Jwt", "OAuth2User",
    "UserDetails", "SecurityContext",
}
INJECTED_ANNOTATIONS = {"AuthenticationPrincipal", "CurrentSecurityContext", "SessionAttribute",
                        "RequestAttribute", "Value", "CookieValue"}
NOT_NULL_ANNOTATIONS = {"NotNull", "NotBlank", "NotEmpty", "NonNull", "Nonnull", "Id", "KotlinNonNull"}
LOMBOK_GETTERS = {"Data", "Getter", "Value"}
LOMBOK_SETTERS = {"Data", "Setter"}


def _uncap_jackson(name: str) -> str:
    """Jackson's default bean naming: lower-case the leading run of capitals."""
    if not name:
        return name
    i = 0
    while i < len(name) and name[i].isupper():
        i += 1
    if i == 0:
        return name
    return name[:i].lower() + name[i:]


def _norm_path(*parts: str) -> str:
    p = "/".join(s.strip("/") for s in parts if s and s.strip("/"))
    return "/" + p if p else "/"


class Extractor:
    _ignored: set | None = None  # @JsonIgnore'd names of the type being described

    def __init__(self, project: JavaProject, bigdecimal: str = "number", context_path: str = "", naming: str = "camel"):
        self.p = project
        self.bigdecimal = bigdecimal
        self.context_path = context_path
        self.naming = naming
        self.types: dict[str, dict] = {}  # ts name -> type schema
        self.ts_names: dict[str, str] = {}  # java fqn -> ts name
        self.pending: list[JType] = []
        self.warnings: list[str] = []
        self._name_counts: dict[str, int] = {}
        for t in project.all_types():
            self._name_counts[t.name] = self._name_counts.get(t.name, 0) + 1

    # ---------------------------------------------------------------- naming
    def ts_name(self, jt: JType) -> str:
        if jt.fqn in self.ts_names:
            return self.ts_names[jt.fqn]
        name = jt.name
        if self._name_counts.get(jt.name, 0) > 1 and "." in jt.qualified:
            # Same simple name in two places (e.g. two controllers each nest a
            # CreateReturnRequest): qualify with the enclosing type, minus "Controller".
            outer = jt.qualified.rsplit(".", 1)[0].replace(".", "")
            name = re.sub(r"Controller$", "", outer) + jt.name
        base, k = name, 2
        while name in self.types or name in self.ts_names.values():
            name = f"{base}{k}"
            k += 1
        self.ts_names[jt.fqn] = name
        return name

    # ---------------------------------------------------------------- types
    def map_type(self, ref: TypeRef, ctx: JType | None, type_params: list[str] = ()) -> dict:
        """Java TypeRef -> contract type node."""
        s = ref.simple
        if ref.dims:
            elem = TypeRef(ref.name, ref.args, ref.dims - 1)
            if ref.dims == 1 and s in ("byte", "Byte"):
                return {"kind": "string", "format": "byte"}  # Jackson writes byte[] as base64
            return {"kind": "array", "items": self.map_type(elem, ctx, type_params)}
        if s in type_params:
            return {"kind": "typeParam", "name": s}
        if s in WRAPPERS:
            return self.map_type(ref.args[0], ctx, type_params) if ref.args else {"kind": "unknown"}
        if s == "Optional":
            inner = self.map_type(ref.args[0], ctx, type_params) if ref.args else {"kind": "unknown"}
            return {**inner, "nullable": True}
        if s in ("OptionalInt", "OptionalLong", "OptionalDouble"):
            return {"kind": "number", "nullable": True}
        if s in ("void", "Void"):
            return {"kind": "void"}
        if s in STRING_TYPES:
            return {"kind": "string"}
        if s in INT_TYPES:
            return {"kind": "number", "format": "integer"}
        if s in FLOAT_TYPES:
            return {"kind": "number"}
        if s == "BigDecimal":
            return {"kind": self.bigdecimal, "format": "decimal"}
        if s in BOOL_TYPES:
            return {"kind": "boolean"}
        if s in DATE_FORMATS:
            return {"kind": "string", "format": DATE_FORMATS[s]}
        if s in LIST_TYPES:
            item = self.map_type(ref.args[0], ctx, type_params) if ref.args else {"kind": "unknown"}
            return {"kind": "array", "items": item}
        if s in MAP_TYPES:
            val = self.map_type(ref.args[-1], ctx, type_params) if ref.args else {"kind": "unknown"}
            if s == "MultiValueMap":
                val = {"kind": "array", "items": val}
            return {"kind": "map", "values": val}
        if s in ("Page", "Slice", "PageImpl"):
            item = self.map_type(ref.args[0], ctx, type_params) if ref.args else {"kind": "unknown"}
            return {"kind": "page", "items": item}
        if s in BINARY_TYPES:
            return {"kind": "binary"}
        if s in UNKNOWN_TYPES:
            return {"kind": "unknown"}
        jt = self.p.resolve(ref.name, ctx)
        if jt is None:
            self.warnings.append(f"Unresolved type '{ref}' (used in {ctx.qualified if ctx else '?'}); emitted as unknown")
            return {"kind": "unknown", "javaType": str(ref)}
        name = self.ts_name(jt)
        if name not in self.types and jt not in self.pending:
            self.pending.append(jt)
        node = {"kind": "ref", "name": name}
        if ref.args:
            node["args"] = [self.map_type(a, ctx, type_params) for a in ref.args]
        return node

    def drain(self) -> None:
        while self.pending:
            jt = self.pending.pop(0)
            name = self.ts_name(jt)
            if name not in self.types:
                self.types[name] = {}  # reserve before recursing (cycles)
                self.types[name] = self.describe(jt)

    def describe(self, jt: JType) -> dict:
        base = {"javaType": jt.fqn, "source": f"{jt.file}:{jt.line}"}
        if jt.doc:
            base["doc"] = jt.doc
        if jt.kind == "enum":
            values = jt.enum_constants
            json_value = any(m.ann("JsonValue") for m in jt.methods)
            out = {"kind": "enum", "values": values, **base}
            if json_value:
                out["note"] = "@JsonValue changes the wire value; values listed are constant names"
            return out
        if jt.type_params:
            base["typeParams"] = jt.type_params
        # @JsonIgnore'd names, filled by record_props/_merge. Saved and restored because
        # map_type() can describe nested types while this one is being built.
        outer, self._ignored = getattr(self, "_ignored", None), set()
        try:
            props = self.record_props(jt) if jt.kind == "record" else self.bean_props(jt)
        finally:
            mine, self._ignored = self._ignored, outer
        ignored = set()
        jip = jt.ann("JsonIgnoreProperties")
        if jip:
            ignored = set(jip.strings("value"))
        props = [p for p in props if p["name"] not in ignored]
        out = {"kind": "object", "properties": props, **base}
        dropped = (mine | ignored) - {p["name"] for p in props}
        if dropped:
            out["ignored"] = sorted(dropped)  # lets the drift check say "@JsonIgnore" instead of "does not exist"
        return out

    def wire_name(self, name: str, owner: JType) -> str:
        """Apply the global/class naming strategy (explicit @JsonProperty names bypass this)."""
        strategy = self.naming
        jn = owner.ann("JsonNaming")
        if jn:
            v = jn.raw_args
            strategy = "snake" if "Snake" in v else "kebab" if "Kebab" in v else "lower" if "LowerCase" in v else \
                "upper_camel" if "UpperCamel" in v else strategy
        if strategy in ("snake", "kebab"):
            sep = "_" if strategy == "snake" else "-"
            return re.sub(r"(?<=[a-z0-9])([A-Z])", sep + r"\1", name).lower()
        if strategy == "lower":
            return name.lower()
        if strategy == "upper_camel":
            return name[:1].upper() + name[1:]
        return name

    def record_props(self, jt: JType) -> list[dict]:
        out = []
        for c in jt.components:
            if c.ann("JsonIgnore"):
                if self._ignored is not None:
                    self._ignored.add(c.name)
                continue
            name = self._json_name(c.ann("JsonProperty")) or self.wire_name(c.name, jt)
            t = self.map_type(c.type, jt, jt.type_params)
            out.append(self._prop(name, t, c.type, c.annotations, None, read=True, write=True))
        return out

    def bean_props(self, jt: JType) -> list[dict]:
        """Jackson's view of a class: getters (read), setters/fields (write), annotations."""
        chain, cur, seen = [], jt, set()
        while cur is not None and cur.fqn not in seen:  # superclass fields come first
            seen.add(cur.fqn)
            chain.insert(0, cur)
            cur = self.p.resolve(cur.extends.name, cur) if cur.extends else None

        props: dict[str, dict] = {}
        for t in chain:
            lombok_get = any(t.ann(a) for a in LOMBOK_GETTERS)
            lombok_set = any(t.ann(a) for a in LOMBOK_SETTERS)
            fields = {f.name: f for f in t.fields if "static" not in f.modifiers}
            getters, setters = {}, {}
            for m in t.methods:
                if "static" in m.modifiers or m.return_type is None:
                    continue
                if "public" not in m.modifiers and t.kind != "interface":
                    continue
                if not m.params and m.return_type.name != "void":
                    g = re.match(r"get([A-Z_$].*)", m.name)
                    i = re.match(r"is([A-Z_$].*)", m.name) if m.return_type.name == "boolean" else None
                    hit = g or i
                    if hit and m.name != "getClass":
                        getters[_uncap_jackson(hit.group(1))] = m
                elif len(m.params) == 1:
                    s = re.match(r"set([A-Z_$].*)", m.name)
                    if s:
                        setters[_uncap_jackson(s.group(1))] = m

            for f in fields.values():
                if "transient" in f.modifiers:
                    continue
                public = "public" in f.modifiers
                has_lombok_getter = lombok_get or f.ann("Getter") is not None
                has_lombok_setter = (lombok_set or f.ann("Setter") is not None) and "final" not in f.modifiers
                prop_name = f.name
                if has_lombok_getter and f.type.name == "boolean" and re.match(r"is[A-Z]", f.name):
                    prop_name = _uncap_jackson(f.name[2:])  # Lombok: boolean isActive -> isActive() -> "active"
                readable = public or has_lombok_getter or prop_name in getters
                if not readable and prop_name not in setters and not has_lombok_setter:
                    continue
                writable = public or has_lombok_setter or prop_name in setters or readable
                getter = getters.pop(prop_name, None)
                setter = setters.pop(prop_name, None)
                anns = list(f.annotations) + (getter.annotations if getter else []) + (setter.annotations if setter else [])
                ref = getter.return_type if getter else f.type
                self._merge(props, prop_name, ref, anns, f, readable, writable, t)
            for pname, g in getters.items():  # computed getters with no backing field
                anns = list(g.annotations) + (setters[pname].annotations if pname in setters else [])
                self._merge(props, pname, g.return_type, anns, None, True, pname in setters, t, doc=g.doc, line=g.line)
                setters.pop(pname, None)
            for pname, s in setters.items():  # write-only
                self._merge(props, pname, s.params[0].type, s.annotations, None, False, True, t, doc=s.doc, line=s.line)
        return [p for p in props.values() if p is not None]

    def _merge(self, props, name, ref, anns, fld, read, write, owner: JType, doc=None, line=None):
        if find_ann(anns, "JsonIgnore") and (find_ann(anns, "JsonIgnore").raw_args.strip() in ("", "true")):
            props.pop(name, None)
            if self._ignored is not None:
                self._ignored.add(name)
            return
        jp = find_ann(anns, "JsonProperty")
        json_name = self._json_name(jp) or self.wire_name(name, owner)
        access = (jp.get("access") or "") if jp else ""
        if "READ_ONLY" in access:
            write = False
        elif "WRITE_ONLY" in access:
            read = False
        if not read and not write:
            return
        t = self.map_type(ref, owner, owner.type_params)
        jf = find_ann(anns, "JsonFormat")
        if jf and "STRING" in (jf.get("shape") or "") and t.get("kind") in ("number", "boolean"):
            t = {"kind": "string", "format": t.get("format")}
        p = self._prop(json_name, t, ref, anns, fld, read=read, write=write)
        if doc and "doc" not in p:
            p["doc"] = doc
        java_name = getattr(fld, "name", None) or name
        if java_name != json_name:
            # Lets the drift check explain renames: TS `sku` vs JSON `sku_code`, TS `isActive` vs `active`.
            p["javaName"] = java_name
            p["renamedBy"] = ("@JsonProperty" if self._json_name(jp)
                              else "naming strategy" if self.wire_name(name, owner) != name
                              else "boolean getter naming (`isX` -> `x`)")
        props[json_name] = p

    def _json_name(self, ann) -> str | None:
        if ann is None:
            return None
        vals = ann.strings("value")
        return vals[0] if vals and vals[0] else None

    def _prop(self, name, t, ref: TypeRef, anns, fld, read: bool, write: bool) -> dict:
        nullable, why = True, None
        nn = next((a for a in anns if a.name in NOT_NULL_ANNOTATIONS), None)
        if ref.name in PRIMITIVES and not ref.dims:
            nullable, why = False, "primitive"
        elif nn is not None:
            nullable, why = False, ("Kotlin non-null type" if nn.name == "KotlinNonNull" else f"@{nn.name}")
        else:
            col = find_ann(anns, "Column") or find_ann(anns, "JoinColumn")
            m2o = find_ann(anns, "ManyToOne") or find_ann(anns, "OneToOne")
            if col and (col.flag("nullable") or "").strip() == "false":
                nullable, why = False, "@Column(nullable = false)"
            elif m2o and (m2o.flag("optional") or "").strip() == "false":
                nullable, why = False, "optional = false"
            elif fld is not None and fld.initializer and fld.initializer.strip() != "null":
                nullable, why = False, "initialized"
            elif t.get("nullable"):
                nullable = True
        out = {"name": name, "type": {k: v for k, v in t.items() if k != "nullable"}, "nullable": nullable}
        if why:
            out["nonNullBecause"] = why
        if find_ann(anns, "Id"):
            out["identifier"] = True  # set from the path or by the server, never required in a body
            if find_ann(anns, "GeneratedValue"):
                out["generated"] = True  # present in responses, absent when creating
        if not read:
            out["writeOnly"] = True
        if not write:
            out["readOnly"] = True
        if fld is not None:
            out["line"] = fld.line
            if fld.doc:
                out["doc"] = fld.doc
        return out

    # ------------------------------------------------------------ endpoints
    def controllers(self) -> list[JType]:
        out = []
        for t in self.p.all_types():
            if t.ann("RestController") or (t.ann("Controller") and t.ann("ResponseBody")):
                out.append(t)
            elif t.ann("Controller") and any(m.ann("ResponseBody") for m in t.methods):
                out.append(t)
        return sorted(out, key=lambda t: (t.file, t.line))

    def endpoints(self) -> list[dict]:
        eps = []
        for ctl in self.controllers():
            base_paths = [""]
            rm = ctl.ann("RequestMapping")
            if rm:
                base_paths = rm.strings("value", "path") or [""]
                if rm.get("value", "path") and not rm.strings("value", "path"):
                    self.warnings.append(f"{ctl.name}: @RequestMapping path is a constant expression; base path unresolved")
            class_auth = ctl.ann("PreAuthorize") or ctl.ann("Secured") or ctl.ann("RolesAllowed")
            whole_controller_body = ctl.ann("RestController") is not None or ctl.ann("ResponseBody") is not None
            for m in ctl.methods:
                eps.extend(self._endpoint(ctl, m, base_paths, class_auth, whole_controller_body))
        return eps

    def _endpoint(self, ctl: JType, m: JMethod, base_paths, class_auth, body_default) -> list[dict]:
        verbs, paths = [], None
        for a in m.annotations:
            if a.name in HTTP_MAPPINGS:
                verbs = [HTTP_MAPPINGS[a.name]]
                paths = a.strings("value", "path")
                if a.get("value", "path") and not paths:
                    self.warnings.append(f"{ctl.name}.{m.name}: mapping path is a constant expression; skipped")
                    return []
                break
            if a.name == "RequestMapping":
                meth = a.get("method") or ""
                verbs = re.findall(r"RequestMethod\.(\w+)", meth) or ["GET"]
                if not meth:
                    self.warnings.append(f"{ctl.name}.{m.name}: @RequestMapping without method= accepts every verb; recorded as GET")
                paths = a.strings("value", "path")
                break
        if not verbs:
            return []
        if not body_default and not m.ann("ResponseBody"):
            return []
        paths = paths or [""]

        path_params, query, headers, body, multipart = [], [], [], None, False
        for prm in m.params:
            simple = prm.type.simple
            if any(prm.ann(a) for a in INJECTED_ANNOTATIONS) or simple in FRAMEWORK_PARAMS:
                continue
            if (pv := prm.ann("PathVariable")) is not None:
                name = (pv.strings("value", "name") or [prm.name])[0]
                path_params.append({"name": name, "type": self.map_type(prm.type, ctl)})
            elif (rb := prm.ann("RequestBody")) is not None:
                req = (rb.flag("required") or "true") != "false"
                body = {"type": self.map_type(prm.type, ctl), "required": req, "contentType": "json"}
            elif (rp := prm.ann("RequestParam")) is not None or (rp := prm.ann("RequestPart")) is not None:
                if simple in ("Map", "MultiValueMap") and not rp.strings("value", "name"):
                    query.append({"name": "*", "type": {"kind": "map", "values": {"kind": "string"}}, "required": False})
                    continue
                name = (rp.strings("value", "name") or [prm.name])[0]
                default = rp.strings("defaultValue")
                required = (rp.flag("required") or "true") != "false" and not default and simple != "Optional"
                t = self.map_type(prm.type, ctl)
                if t["kind"] == "binary" or rp.name == "RequestPart" or (t["kind"] == "array" and t["items"]["kind"] == "binary"):
                    multipart = True
                q = {"name": name, "type": {k: v for k, v in t.items() if k != "nullable"}, "required": required}
                if default:
                    q["default"] = default[0]
                query.append(q)
            elif (rh := prm.ann("RequestHeader")) is not None:
                name = (rh.strings("value", "name") or [prm.name])[0]
                headers.append({"name": name, "required": (rh.flag("required") or "true") != "false"})
            elif simple == "Pageable":
                for n, k in (("page", "integer"), ("size", "integer"), ("sort", None)):
                    query.append({"name": n, "type": {"kind": "number", "format": k} if k else {"kind": "string"}, "required": False})
            elif simple == "Sort":
                query.append({"name": "sort", "type": {"kind": "string"}, "required": False})
            else:
                t = self.map_type(prm.type, ctl)
                if t["kind"] in ("string", "number", "boolean", "enum") or (t["kind"] == "ref" and self.types.get(t["name"], {}).get("kind") == "enum"):
                    # Spring binds an unannotated simple parameter as an optional query param.
                    query.append({"name": prm.name, "type": t, "required": False})
                elif t["kind"] == "ref":
                    # @ModelAttribute / unannotated object: its properties come from the query string.
                    query.append({"name": "*", "type": t, "required": False, "modelAttribute": True})
        if multipart and body is None:
            body = {"type": {"kind": "unknown"}, "required": True, "contentType": "multipart"}
        elif multipart:
            body["contentType"] = "multipart"

        ret = m.return_type or TypeRef("void")
        rtype = self.map_type(ret, ctl)
        fmt = "json"
        if rtype["kind"] == "void":
            fmt = "none"
        elif rtype["kind"] == "binary" or (rtype["kind"] == "string" and rtype.get("format") == "byte"):
            fmt = "binary"
        elif ret.simple == "String" and not ret.dims:
            fmt = "text"  # Spring writes a bare String as text/plain, not JSON
        elif ret.simple in ("ResponseEntity", "HttpEntity") and ret.args and ret.args[0].simple == "String":
            fmt = "text"
        if ret.simple in ("ResponseEntity", "HttpEntity") and (not ret.args or ret.args[0].name == "?"):
            self.warnings.append(f"{ctl.name}.{m.name}: returns ResponseEntity<?>; response type unknown")
        produces = None
        for a in m.annotations:
            if a.name in HTTP_MAPPINGS or a.name == "RequestMapping":
                pr = a.get("produces") or ""
                if "TEXT" in pr or "text/" in pr:
                    fmt = "text"
                elif "OCTET" in pr or "PDF" in pr or "IMAGE" in pr or "application/pdf" in pr:
                    fmt = "binary"
                produces = pr or None

        auth = m.ann("PreAuthorize") or m.ann("Secured") or m.ann("RolesAllowed") or class_auth
        status = m.ann("ResponseStatus")
        out = []
        for base in base_paths:
            for sub in paths:
                for verb in verbs:
                    path = _norm_path(self.context_path, base, sub)
                    ep = {
                        "id": f"{ctl.name}.{m.name}",
                        "controller": ctl.name,
                        "operation": m.name,
                        "method": verb,
                        "path": path,
                        "pathParams": path_params,
                        "queryParams": query,
                        "response": {"type": {k: v for k, v in rtype.items() if k != "nullable"}, "format": fmt,
                                     "nullable": bool(rtype.get("nullable"))},
                        "source": f"{ctl.file}:{m.line}",
                    }
                    declared = set(re.findall(r"\{([^}:]+)(?::[^}]*)?\}", path))
                    missing = declared - {p["name"] for p in path_params}
                    if missing:
                        self.warnings.append(f"{ep['id']}: path variables {sorted(missing)} have no @PathVariable parameter")
                    if body:
                        ep["body"] = body
                    if headers:
                        ep["headers"] = headers
                    if auth:
                        ep["auth"] = auth.raw_args.strip()
                    if status:
                        ep["status"] = status.raw_args.strip()
                    if produces:
                        ep["produces"] = produces
                    if m.doc:
                        ep["doc"] = m.doc
                    out.append(ep)
        return out


def find_java_root(path: Path) -> Path:
    """Source root: src/main/java, src/main/kotlin, or src/main when a project has both."""
    for base in (path, path / "backend"):
        main = base / "src" / "main"
        java, kotlin = (main / "java").is_dir(), (main / "kotlin").is_dir()
        if java and kotlin:
            return main
        if java or kotlin:
            return main / ("java" if java else "kotlin")
    return path


def resources_root(src_root: Path, backend: Path) -> Path:
    if src_root.name in ("java", "kotlin"):
        return src_root.parent / "resources"
    if src_root.name == "main" and (src_root / "resources").is_dir():
        return src_root / "resources"
    return backend


def detect_settings(path: Path) -> dict:
    """Read the bits of application.properties/yml that change the wire format."""
    found: dict = {}
    if not path.is_dir():
        return found
    for res in sorted(path.rglob("application*.*")):
        if "test" in res.parts or res.suffix not in (".properties", ".yml", ".yaml"):
            continue
        text = res.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^\s*server\.servlet\.context-path\s*[=:]\s*(\S+)", text, re.M) or \
            re.search(r"servlet:\s*\n\s+context-path:\s*(\S+)", text)
        if m and "context_path" not in found:
            found["context_path"] = m.group(1).strip("\"'")
        m = re.search(r"property-naming-strategy\s*[=:]\s*(\S+)", text)
        if m and "naming" not in found:
            v = m.group(1).upper()
            found["naming"] = "snake" if "SNAKE" in v else "kebab" if "KEBAB" in v else \
                "lower" if "LOWER_CASE" in v else "upper_camel" if "UPPER_CAMEL" in v else "camel"
        if re.search(r"WRITE_BIGDECIMAL_AS_STRING\s*[=:]\s*true|write-bigdecimal-as-string\s*[=:]\s*true", text, re.I):
            found["bigdecimal"] = "string"
    return found


def build_contract(backend: Path, bigdecimal: str | None = None, context_path: str | None = None,
                   naming: str | None = None) -> dict:
    java_root = find_java_root(backend)
    res_root = resources_root(java_root, backend)
    detected = detect_settings(res_root)
    context_path = context_path if context_path is not None else detected.get("context_path", "")
    naming = naming or detected.get("naming", "camel")
    bigdecimal = bigdecimal or detected.get("bigdecimal", "number")
    project = JavaProject(java_root)
    ex = Extractor(project, bigdecimal=bigdecimal, context_path=context_path, naming=naming)
    eps = ex.endpoints()
    ex.drain()
    return {
        "contractVersion": 1,
        "generator": "api-contract-sync/extract_spring.py",
        "backend": str(backend),
        "javaRoot": str(java_root),
        "contextPath": context_path,
        "options": {"bigdecimal": bigdecimal, "naming": naming,
                    "detectedFromConfig": sorted(k for k in detected)},
        "stats": {"javaFiles": len(project.files), "controllers": len({e["controller"] for e in eps}),
                  "endpoints": len(eps), "types": len(ex.types)},
        "endpoints": eps,
        "types": dict(sorted(ex.types.items())),
        "warnings": sorted(set(ex.warnings)) + project.errors,
    }


def type_str(t: dict) -> str:
    k = t.get("kind")
    if k == "ref":
        args = t.get("args")
        return t["name"] + (f"<{', '.join(type_str(a) for a in args)}>" if args else "")
    if k == "array":
        return type_str(t["items"]) + "[]"
    if k == "map":
        return f"Map<string, {type_str(t['values'])}>"
    if k == "page":
        return f"Page<{type_str(t['items'])}>"
    if k == "typeParam":
        return t["name"]
    return k + (f"({t['format']})" if t.get("format") else "")


def summary(contract: dict) -> str:
    lines = [f"# API contract — {contract['stats']['endpoints']} endpoints, {contract['stats']['types']} types",
             f"backend: {contract['backend']}  context-path: '{contract['contextPath']}'", ""]
    cur = None
    for e in contract["endpoints"]:
        if e["controller"] != cur:
            cur = e["controller"]
            lines.append(f"\n## {cur}")
        q = ", ".join(("" if p["required"] else "?") + p["name"] for p in e["queryParams"])
        body = f" body={type_str(e['body']['type'])}" if e.get("body") else ""
        lines.append(f"  {e['method']:<6} {e['path']}{'  ?' + q if q else ''}{body} -> {type_str(e['response']['type'])}"
                     f"{' [' + e['response']['format'] + ']' if e['response']['format'] != 'json' else ''}")
    if contract["warnings"]:
        lines.append(f"\n## Warnings ({len(contract['warnings'])})")
        lines += [f"  - {w}" for w in contract["warnings"]]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("backend", type=Path, help="Spring Boot project root or a directory of .java files")
    ap.add_argument("-o", "--output", type=Path, help="write contract JSON here (default: stdout)")
    ap.add_argument("--context-path", default=None, help="override server.servlet.context-path")
    ap.add_argument("--bigdecimal", choices=["number", "string"], default=None,
                    help="how BigDecimal is serialized (default: number, or string when application config says so)")
    ap.add_argument("--naming", choices=["camel", "snake", "kebab", "lower", "upper_camel"], default=None,
                    help="Jackson property naming strategy (default: read from application config, else camel)")
    ap.add_argument("--summary", action="store_true", help="print a human-readable endpoint list to stderr")
    a = ap.parse_args(argv)
    if not a.backend.exists():
        ap.error(f"{a.backend} does not exist")
    contract = build_contract(a.backend, a.bigdecimal, a.context_path, a.naming)
    text = json.dumps(contract, indent=2)
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(text, encoding="utf-8")
        s = contract["stats"]
        print(f"Wrote {a.output}: {s['endpoints']} endpoints from {s['controllers']} controllers, "
              f"{s['types']} types, {len(contract['warnings'])} warnings", file=sys.stderr)
    else:
        print(text)
    if a.summary:
        print(summary(contract), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
