#!/usr/bin/env python3
"""Build a contract from an OpenAPI 3.x / Swagger 2.0 document.

This is how non-Java backends are supported: FastAPI, NestJS, ASP.NET (Swashbuckle /
NSwag), Go (swag), Laravel, Django REST framework, Rails (rswag) and Spring
(springdoc) can all export OpenAPI. The result has the same shape as
extract_spring.py's contract, so check_drift.py and generate_ts.py work unchanged.

Usage:
    python extract_openapi.py openapi.json [-o contract.json] [--context-path /api]

JSON is read with the standard library. YAML needs PyYAML (pip install pyyaml);
without it, export the spec as JSON instead.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

METHODS = ("get", "post", "put", "patch", "delete")


def load_spec(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError:
            raise SystemExit(f"{path}: reading YAML needs PyYAML (pip install pyyaml), or export the spec as JSON")
        return yaml.safe_load(text)
    return json.loads(text)


def is_openapi(doc) -> bool:
    return isinstance(doc, dict) and ("openapi" in doc or "swagger" in doc) and "paths" in doc


def is_named(s) -> bool:
    """Schemas that become their own contract type (objects and string enums);
    arrays, scalars and maps are inlined where they are used."""
    if not isinstance(s, dict):
        return False
    return bool(s.get("properties") or s.get("allOf") or ("enum" in s and s.get("type") in (None, "string")))


def ts_ident(name: str) -> str:
    """'Page«Order»', 'app.models.Order', 'Body_create_item' -> valid TS type names."""
    name = re.sub(r"[^\w$]+", "_", name).strip("_") or "Anonymous"
    return name if re.match(r"[A-Za-z_$]", name) else "_" + name


def pascal(*parts: str) -> str:
    words = [w for p in parts for w in re.split(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])", p) if w]
    return "".join(w[:1].upper() + w[1:] for w in words) or "Anonymous"


def camel(s: str) -> str:
    p = pascal(s)
    return p[:1].lower() + p[1:]


class OpenApi:
    def __init__(self, spec: dict, label: str, context_path: str | None):
        self.spec = spec
        self.label = label
        self.v2 = "swagger" in spec
        self.schemas = (spec.get("definitions") if self.v2 else spec.get("components", {}).get("schemas")) or {}
        self.types: dict[str, dict] = {}
        self.warnings: list[str] = []
        self._inlining: set[str] = set()
        self._schema_names = {ts_ident(n) for n in self.schemas}
        self._inline_src: dict[str, int] = {}
        self.base = self._base_path() if context_path is None else context_path.rstrip("/")

    # ------------------------------------------------------------ helpers
    def _base_path(self) -> str:
        if self.v2:
            return (self.spec.get("basePath") or "").rstrip("/")
        servers = self.spec.get("servers") or []
        if not servers:
            return ""
        url = re.sub(r"\{[^}]*\}", "", servers[0].get("url", ""))
        return (urlparse(url).path if "://" in url else url).rstrip("/")

    def deref(self, obj):
        seen = 0
        while isinstance(obj, dict) and "$ref" in obj and seen < 20:
            ref = obj["$ref"]
            if not ref.startswith("#/"):
                self.warnings.append(f"external $ref not followed: {ref}")
                return {}
            node = self.spec
            for part in ref[2:].split("/"):
                node = node.get(part.replace("~1", "/").replace("~0", "~"), {}) if isinstance(node, dict) else {}
            obj, seen = node, seen + 1
        return obj

    @staticmethod
    def ref_name(ref: str) -> str:
        return ts_ident(ref.rsplit("/", 1)[-1])

    # ------------------------------------------------------------ schemas -> type nodes
    def node(self, s: dict | None, ctx: str) -> tuple[dict, bool]:
        """Schema -> (contract type node, nullable)."""
        if not isinstance(s, dict) or not s:
            return {"kind": "unknown"}, True
        nullable = bool(s.get("nullable") or s.get("x-nullable"))
        if "$ref" in s:
            ref = s["$ref"]
            target = self.deref(s)
            if ("/schemas/" in ref or "/definitions/" in ref) and is_named(target):
                return {"kind": "ref", "name": self.ref_name(ref)}, nullable
            if ref in self._inlining:  # recursive alias: give up rather than loop
                return {"kind": "unknown"}, True
            self._inlining.add(ref)
            try:  # alias of an array/scalar/map schema: inline it
                n, inner_null = self.node(target, ctx)
            finally:
                self._inlining.discard(ref)
            return n, nullable or inner_null
        for key in ("anyOf", "oneOf"):
            if key in s:
                opts = [o for o in s[key] if not (isinstance(o, dict) and o.get("type") == "null")]
                nullable = nullable or len(opts) < len(s[key])
                if len(opts) == 1:
                    n, inner_null = self.node(opts[0], ctx)
                    return n, nullable or inner_null
                return {"kind": "unknown"}, nullable
        if "allOf" in s:
            parts = s["allOf"]
            if len(parts) == 1 and not s.get("properties"):
                n, inner_null = self.node(parts[0], ctx)
                return n, nullable or inner_null
            name = self._register_object(ctx, s)
            return {"kind": "ref", "name": name}, nullable
        t = s.get("type")
        if isinstance(t, list):  # OpenAPI 3.1: ["string", "null"]
            nullable = nullable or "null" in t
            rest = [x for x in t if x != "null"]
            t = rest[0] if len(rest) == 1 else None
        if "enum" in s and t in (None, "string"):
            name = self.inline_name(ctx, s)
            if name not in self.types:
                self.types[name] = {"kind": "enum", "values": [str(v) for v in s["enum"] if v is not None],
                                    "source": f"{self.label} (inline enum)"}
            return {"kind": "ref", "name": name}, nullable or None in s["enum"]
        fmt = s.get("format")
        if t == "string":
            if fmt in ("binary",):
                return {"kind": "binary"}, nullable
            if fmt in ("date", "date-time", "byte"):
                return {"kind": "string", "format": fmt}, nullable
            return {"kind": "string"}, nullable
        if t == "integer":
            return {"kind": "number", "format": "integer"}, nullable
        if t == "number":
            return ({"kind": "number", "format": "decimal"} if fmt == "decimal" else {"kind": "number"}), nullable
        if t == "boolean":
            return {"kind": "boolean"}, nullable
        if t == "file":  # Swagger 2.0
            return {"kind": "binary"}, nullable
        if t == "array":
            items, _ = self.node(s.get("items"), ctx + "Item")
            return {"kind": "array", "items": items}, nullable
        if s.get("properties") or t == "object":
            if s.get("properties"):
                return {"kind": "ref", "name": self._register_object(ctx, s)}, nullable
            ap = s.get("additionalProperties")
            if isinstance(ap, dict):
                vals, _ = self.node(ap, ctx + "Value")
                return {"kind": "map", "values": vals}, nullable
            return {"kind": "map", "values": {"kind": "unknown"}}, nullable
        return {"kind": "unknown"}, nullable

    def inline_name(self, ctx: str, s: dict) -> str:
        """Name for an inline enum/object; never one of the document's own schema names,
        and reused only for an identical inline schema."""
        base = ts_ident(pascal(ctx))
        name, n = base, 2
        while name in self._schema_names or (name in self._inline_src and self._inline_src[name] != id(s)):
            name, n = f"{base}{n}", n + 1
        self._inline_src[name] = id(s)
        return name

    def _register_object(self, ctx: str, s: dict) -> str:
        name = self.inline_name(ctx, s)
        if name not in self.types:
            self.types[name] = {}  # reserve first: schemas can be recursive
            self.types[name] = self.object_type(name, s, f"{self.label} (inline schema)")
        return name

    def _merged(self, s: dict, depth: int = 0) -> tuple[dict, set]:
        """Flatten allOf into one {prop: schema} map and a required set."""
        props, required = {}, set(s.get("required") or [])
        for part in s.get("allOf") or []:
            sub = self.deref(part) if "$ref" in part else part
            if depth < 10:
                p, r = self._merged(sub, depth + 1)
                props.update(p)
                required |= r
        props.update(s.get("properties") or {})
        return props, required

    def object_type(self, name: str, s: dict, source: str) -> dict:
        s = self.deref(s)
        if "enum" in s and s.get("type") in (None, "string"):
            return {"kind": "enum", "values": [str(v) for v in s["enum"] if v is not None], "source": source}
        props, required = self._merged(s)
        out = []
        for pname, ps in props.items():
            ps = ps if isinstance(ps, dict) else {}
            node, nullable = self.node(ps, f"{name}_{pname}")
            raw = self.deref(ps) if "$ref" in ps else ps
            # nullable: may be missing or null (what the drift check needs);
            # optional / nullValue: the two separately, for generating `x?: T | null` precisely.
            p = {"name": pname, "type": node, "nullable": nullable or pname not in required,
                 "optional": pname not in required, "nullValue": nullable}
            if pname in required and not nullable:
                p["nonNullBecause"] = "required in the OpenAPI schema"
            if raw.get("readOnly"):
                p["readOnly"] = True
            if raw.get("writeOnly"):
                p["writeOnly"] = True
            if raw.get("description"):
                p["doc"] = str(raw["description"]).strip().split("\n")[0]
            out.append(p)
        td = {"kind": "object", "properties": out, "source": source}
        if s.get("description"):
            td["doc"] = str(s["description"]).strip().split("\n")[0]
        return td

    def all_schemas(self) -> None:
        for raw_name, s in self.schemas.items():
            name = ts_ident(raw_name)
            if name in self.types and self.types[name]:
                continue
            if not is_named(s):
                continue  # aliases (arrays, scalars, maps) are inlined where referenced
            self.types[name] = {}
            pointer = "definitions" if self.v2 else "components/schemas"
            self.types[name] = self.object_type(name, s, f"{self.label}#/{pointer}/{raw_name}")

    # ------------------------------------------------------------ operations -> endpoints
    def endpoints(self) -> list[dict]:
        eps, seen_ids = [], set()
        security_default = bool(self.spec.get("security"))
        for path, item in (self.spec.get("paths") or {}).items():
            item = self.deref(item)
            shared = item.get("parameters") or []
            for method in METHODS:
                op = item.get(method)
                if not isinstance(op, dict):
                    continue
                params = {}
                for prm in list(shared) + list(op.get("parameters") or []):
                    prm = self.deref(prm)
                    if prm.get("name"):
                        params[(prm.get("in"), prm["name"])] = prm
                tag = (op.get("tags") or ["Default"])[0]
                controller = ts_ident(pascal(tag))
                op_id = op.get("operationId") or f"{method} {path}"
                operation = ts_ident(camel(op_id))
                eid = f"{controller}.{operation}"
                n = 2
                while eid in seen_ids:
                    eid = f"{controller}.{operation}{n}"
                    n += 1
                seen_ids.add(eid)
                full = (self.base + "/" + path.lstrip("/")).rstrip("/") or "/"
                ctx = pascal(operation)
                ep = {
                    "id": eid, "controller": controller, "operation": eid.split(".", 1)[1],
                    "method": method.upper(), "path": full,
                    "pathParams": [], "queryParams": [], "headers": [],
                    "source": f"{self.label} {method.upper()} {path}",
                }
                body_from_params = None
                for (where, pname), prm in params.items():
                    schema = prm.get("schema") if not self.v2 or "schema" in prm else prm
                    if where == "path":
                        t, _ = self.node(schema, ctx + pascal(pname))
                        ep["pathParams"].append({"name": pname, "type": t})
                    elif where == "query":
                        t, _ = self.node(schema, ctx + pascal(pname))
                        q = {"name": pname, "type": t, "required": bool(prm.get("required"))}
                        if isinstance(schema, dict) and "default" in schema:
                            q["default"] = str(schema["default"])
                        ep["queryParams"].append(q)
                    elif where == "header":
                        ep["headers"].append({"name": pname, "required": bool(prm.get("required"))})
                    elif where == "body":  # Swagger 2.0
                        t, _ = self.node(prm.get("schema"), ctx + "Body")
                        body_from_params = {"type": t, "required": bool(prm.get("required")), "contentType": "json"}
                    elif where == "formData":
                        body_from_params = {"type": {"kind": "binary"}, "required": bool(prm.get("required")),
                                            "contentType": "multipart"}
                body = body_from_params or self._request_body(op, ctx)
                if body:
                    ep["body"] = body
                ep["response"], ep["status"] = self._response(op, ctx)
                if op.get("security") or (security_default and op.get("security") is None):
                    ep["auth"] = "secured"
                doc = op.get("summary") or op.get("description")
                if doc:
                    ep["doc"] = str(doc).strip().split("\n")[0]
                eps.append(ep)
        return eps

    def _request_body(self, op: dict, ctx: str) -> dict | None:
        rb = self.deref(op.get("requestBody"))
        if not isinstance(rb, dict) or not rb.get("content"):
            return None
        content = rb["content"]
        for mt, media in content.items():
            if mt == "application/json" or mt.endswith("+json"):
                t, _ = self.node((media or {}).get("schema"), ctx + "Body")
                return {"type": t, "required": bool(rb.get("required")), "contentType": "json"}
        for mt in content:
            if mt.startswith("multipart/") or mt == "application/x-www-form-urlencoded":
                return {"type": {"kind": "binary"}, "required": bool(rb.get("required")), "contentType": "multipart"}
        return None

    def _response(self, op: dict, ctx: str) -> tuple[dict, str | None]:
        responses = op.get("responses") or {}
        codes = sorted((c for c in responses if str(c).startswith("2")), key=str) or \
            (["default"] if "default" in responses else [])
        if not codes:
            return {"type": {"kind": "unknown"}, "format": "json", "nullable": False}, None
        code = str(codes[0])
        r = self.deref(responses[codes[0]]) or {}
        if self.v2:
            if "schema" not in r:
                return {"type": {"kind": "void"}, "format": "none", "nullable": False}, code
            t, nullable = self.node(r["schema"], ctx + "Response")
            produces = op.get("produces") or self.spec.get("produces") or ["application/json"]
            fmt = "json" if any("json" in p for p in produces) else "text" if any(p.startswith("text/") for p in produces) else "binary"
            return {"type": t, "format": fmt, "nullable": nullable}, code
        content = r.get("content") or {}
        if code == "204" or not content:
            return {"type": {"kind": "void"}, "format": "none", "nullable": False}, code
        for mt, media in content.items():
            if mt == "application/json" or mt.endswith("+json") or mt == "*/*":
                t, nullable = self.node((media or {}).get("schema"), ctx + "Response")
                return {"type": t, "format": "json", "nullable": nullable}, code
        mt = next(iter(content))
        if mt.startswith("text/"):
            return {"type": {"kind": "string"}, "format": "text", "nullable": False}, code
        return {"type": {"kind": "binary"}, "format": "binary", "nullable": False}, code


def build_contract_from_openapi(spec: dict, label: str = "openapi.json", context_path: str | None = None) -> dict:
    o = OpenApi(spec, label, context_path)
    o.all_schemas()
    eps = o.endpoints()
    types = {k: v for k, v in o.types.items() if v}
    return {
        "contractVersion": 1,
        "generator": "api-contract-sync/extract_openapi.py",
        "backend": label,
        "javaRoot": "",
        "contextPath": o.base,
        "options": {"bigdecimal": "number", "naming": "as-declared", "detectedFromConfig": [],
                    "source": f"openapi {spec.get('openapi') or spec.get('swagger')}"},
        "stats": {"controllers": len({e["controller"] for e in eps}), "endpoints": len(eps), "types": len(types)},
        "endpoints": eps,
        "types": dict(sorted(types.items())),
        "warnings": sorted(set(o.warnings)),
    }


def load_any(source: Path, bigdecimal: str | None = None, context_path: str | None = None,
             naming: str | None = None) -> dict:
    """A backend directory, an OpenAPI/Swagger file, or a saved contract JSON -> contract."""
    source = Path(source)
    if source.is_dir():
        try:
            from .extract_spring import build_contract
        except ImportError:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from extract_spring import build_contract  # noqa: E402
        return build_contract(source, bigdecimal, context_path, naming)
    doc = load_spec(source)
    if is_openapi(doc):
        return build_contract_from_openapi(doc, source.as_posix(), context_path)
    if isinstance(doc, dict) and "contractVersion" in doc:
        return doc
    raise SystemExit(f"{source}: not a backend directory, an OpenAPI/Swagger document, or a contract JSON")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", type=Path, help="OpenAPI 3.x or Swagger 2.0 document (.json, or .yaml with PyYAML)")
    ap.add_argument("-o", "--output", type=Path, help="write contract JSON here (default: stdout)")
    ap.add_argument("--context-path", default=None, help="override the base path taken from servers[0] / basePath")
    a = ap.parse_args(argv)
    doc = load_spec(a.spec)
    if not is_openapi(doc):
        ap.error(f"{a.spec} is not an OpenAPI/Swagger document")
    contract = build_contract_from_openapi(doc, a.spec.as_posix(), a.context_path)
    text = json.dumps(contract, indent=2)
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(text, encoding="utf-8")
        s = contract["stats"]
        print(f"Wrote {a.output}: {s['endpoints']} endpoints, {s['types']} types, "
              f"{len(contract['warnings'])} warnings", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
