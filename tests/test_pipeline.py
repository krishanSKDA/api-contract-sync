"""Regression tests for api-contract-sync. Run: python -m unittest discover -s tests

Uses the fixtures in tests/fixtures, whose frontends have drift planted on purpose.
Each planted bug must be reported, and nothing else at error level.

The same file runs in the Claude skill (modules in scripts/) and in the Python
package (modules in src/api_contract_sync/); tools/sync_skill.py copies it over.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / "scripts" / "check_drift.py").exists():  # skill layout
    sys.path.insert(0, str(ROOT / "scripts"))
    import check_drift
    import extract_openapi
    import extract_spring
    import generate_ts
    import ts_parser
else:  # package layout (src/ checkout or installed)
    sys.path.insert(0, str(ROOT / "src"))
    from api_contract_sync import check_drift, extract_openapi, extract_spring, generate_ts, ts_parser

Checker = check_drift.Checker
build_contract = extract_spring.build_contract
Gen = generate_ts.Gen
TsProject, normalize_url, PLACEHOLDER = ts_parser.TsProject, ts_parser.normalize_url, ts_parser.PLACEHOLDER

FIXTURE = ROOT / "tests" / "fixtures" / "shop-app"


class ExtractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = build_contract(FIXTURE / "backend")

    def ep(self, method, path):
        return next(e for e in self.c["endpoints"] if e["method"] == method and e["path"] == path)

    def test_endpoints(self):
        got = {(e["method"], e["path"]) for e in self.c["endpoints"]}
        self.assertEqual(got, {
            ("GET", "/api/customers"), ("GET", "/api/orders"), ("GET", "/api/orders/{id}"),
            ("POST", "/api/orders"), ("PATCH", "/api/orders/{id}/status"), ("DELETE", "/api/orders/{id}"),
            ("GET", "/api/orders/{id}/receipt"),
        })

    def test_params_and_formats(self):
        self.assertEqual(self.ep("DELETE", "/api/orders/{id}")["pathParams"][0]["name"], "id")  # @PathVariable("id") Long orderId
        self.assertEqual(self.ep("DELETE", "/api/orders/{id}")["response"]["format"], "none")
        self.assertEqual(self.ep("GET", "/api/orders/{id}/receipt")["response"]["format"], "text")
        self.assertEqual(self.ep("GET", "/api/orders")["response"]["type"]["kind"], "page")
        q = {p["name"]: p for p in self.ep("GET", "/api/orders")["queryParams"]}
        self.assertEqual(set(q), {"status", "page", "size", "sort"})  # Pageable expands
        self.assertFalse(q["status"]["required"])
        cq = self.ep("GET", "/api/customers")["queryParams"][0]
        self.assertFalse(cq["required"])  # defaultValue makes it optional
        self.assertEqual(self.ep("POST", "/api/orders")["body"]["type"], {"kind": "ref", "name": "CreateOrderRequest"})

    def test_entity_properties(self):
        props = {p["name"]: p for p in self.c["types"]["Order"]["properties"]}
        self.assertNotIn("internalNote", props)  # @JsonIgnore
        self.assertIn("paid", props)  # boolean isPaid() getter
        self.assertTrue(props["id"]["generated"])
        self.assertFalse(props["customerName"]["nullable"])  # @Column(nullable = false)
        self.assertEqual(props["total"]["type"], {"kind": "number", "format": "decimal"})
        self.assertEqual(props["createdAt"]["type"]["format"], "date-time")
        self.assertEqual(self.c["types"]["OrderStatus"]["values"], ["PENDING", "PAID", "SHIPPED", "CANCELLED"])

    def test_record_components(self):
        props = {p["name"]: p for p in self.c["types"]["CreateOrderRequest"]["properties"]}
        self.assertEqual(list(props), ["customerName", "lines", "note"])
        self.assertFalse(props["customerName"]["nullable"])  # @NotBlank


class DriftTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        contract = build_contract(FIXTURE / "backend")
        fe = TsProject(FIXTURE / "frontend" / "src", [], {})
        cls.ch = Checker(contract, fe, strict_nulls=False)
        cls.ch.run()
        cls.f = list(cls.ch.findings.values())

    def has(self, sev, code, needle):
        hits = [f for f in self.f if f.severity == sev and f.code == code and needle in f.message]
        self.assertTrue(hits, f"expected {sev}/{code} containing {needle!r}; got:\n" +
                        "\n".join(f"{f.severity} {f.code} {f.message}" for f in self.f))

    def test_planted_errors(self):
        self.has("error", "endpoint-missing", "/api/orders/{}/cancel")
        self.has("error", "method-mismatch", "PATCH")
        self.has("error", "page-vs-array", "Spring Page")
        self.has("error", "text-as-json", "/receipt")
        self.has("error", "type-mismatch", "Order.total")
        self.has("error", "type-mismatch", "Order.createdAt")
        self.has("error", "field-not-sent", "customer_name")
        self.has("error", "field-not-sent", "phone")
        self.has("error", "enum-mismatch", "REFUNDED")

    def test_planted_warnings(self):
        self.has("warning", "enum-incomplete", "CANCELLED")
        self.has("warning", "field-ignored", "items")

    def test_no_unexpected_errors(self):
        errors = [f for f in self.f if f.severity == "error"]
        self.assertEqual(len(errors), 9, "\n".join(f.message for f in errors))

    def test_error_path_cast_ignored(self):
        # fetchOrders casts the error body to { message?: string } inside `if (!res.ok)`.
        self.assertFalse([f for f in self.f if "message" in f.message])

    def test_rename_hint(self):
        f = next(f for f in self.f if "customer_name" in f.message)
        self.assertIn("customerName", f.hint or "")


class ErpDriftTest(unittest.TestCase):
    """16-controller fixture; bugs B1-B12 and decoys D1-D4 are listed in build_erp_app.py."""

    @classmethod
    def setUpClass(cls):
        root = ROOT / "tests" / "fixtures" / "erp-app"
        cls.contract = build_contract(root / "backend")
        ch = Checker(cls.contract, TsProject(root / "frontend" / "src", [], {}), strict_nulls=False)
        ch.run()
        cls.f = [f for f in ch.findings.values() if f.severity != "info"]

    def find(self, code, needle):
        hits = [f for f in self.f if f.code == code and needle in f.message]
        self.assertTrue(hits, f"expected {code} containing {needle!r}; got:\n" +
                        "\n".join(f"{f.severity} {f.code} {f.message}" for f in self.f))
        return hits[0]

    def test_contract_size(self):
        self.assertEqual(self.contract["stats"]["controllers"], 16)

    def test_planted_bugs(self):
        self.assertIn("sku_code", self.find("field-not-sent", "Product.sku").hint)            # B1
        self.assertIn("`active`", self.find("field-not-sent", "Product.isActive").hint)      # B2
        self.assertIn("contactEmail", self.find("field-not-sent", "Supplier.email").hint)    # B3
        self.find("type-mismatch", "Invoice.total")                                          # B4
        self.find("text-as-json", "/api/invoices/{id}/print")                                # B5
        self.find("enum-mismatch", "'BANK'")                                                 # B6
        self.find("type-mismatch", "Refund.amount")                                          # B7
        self.find("page-vs-array", "StockMovement[]")                                        # B8
        self.assertIn("/approval", self.find("endpoint-missing", "/approve").hint)           # B9
        self.find("field-not-sent", "@JsonIgnore")                                           # B10
        self.find("method-mismatch", "/api/shifts/{}/close")                                 # B11
        self.find("field-ignored", "NewCoupon.expiry")                                       # B12

    def test_one_error_per_problem(self):
        # List and single-item endpoints share a TS line: reported once, not as `X[].f` + `X.f`.
        errors = [f for f in self.f if f.severity == "error"]
        self.assertFalse([f for f in errors if "[]." in f.message])
        self.assertEqual(len(errors), 12, "\n".join(f.message for f in errors))

    def test_decoys_not_flagged(self):
        for needle in ("tracking_no", "Discount", "Payment.amount", "TaxRate"):          # D1-D4
            self.assertFalse([f for f in self.f if needle in f.message], needle)


class JsFrontendTest(unittest.TestCase):
    """Plain JS, Vue SFC and Svelte frontends against the shop-app backend."""

    @classmethod
    def setUpClass(cls):
        fe = TsProject(ROOT / "tests" / "fixtures" / "shop-app-js" / "src", [], {})
        cls.files = sorted(f.rel for f in fe.files)
        ch = Checker(build_contract(FIXTURE / "backend"), fe, strict_nulls=False)
        ch.run()
        cls.f = list(ch.findings.values())

    def hit(self, code, needle):
        return [f for f in self.f if f.code == code and needle in (f.message + (f.frontend or ""))]

    def test_files_scanned(self):
        # test files, minified files and public/ are skipped
        self.assertEqual(self.files, ["api/orders.js", "components/CustomerSearch.svelte", "components/OrderList.vue"])

    def test_js_findings(self):
        self.assertTrue(self.hit("method-mismatch", "api/orders.js:20"))
        self.assertTrue(self.hit("endpoint-missing", "/cancel"))
        self.assertTrue(self.hit("text-as-json", "/receipt"))
        self.assertTrue(self.hit("field-ignored", "items"))

    def test_vue_script_only_with_original_lines(self):
        self.assertTrue(self.hit("endpoint-missing", "components/OrderList.vue:17"))     # /api/customer typo
        self.assertFalse([f for f in self.f if "not-a-call" in f.message])                # fetch text in <template>
        self.assertFalse([f for f in self.f if "OrderList.vue" in (f.frontend or "") and "status" in f.message])

    def test_svelte_call_matched(self):
        self.assertFalse([f for f in self.f if "CustomerSearch" in (f.frontend or "")])
        self.assertEqual(len([f for f in self.f if f.severity == "error"]), 4)


class KotlinTest(unittest.TestCase):
    """The shop backend rewritten in Kotlin must yield the same drift as the Java one."""

    @classmethod
    def setUpClass(cls):
        cls.c = build_contract(ROOT / "tests" / "fixtures" / "shop-app-kotlin" / "backend")
        ch = Checker(cls.c, TsProject(FIXTURE / "frontend" / "src", [], {}), strict_nulls=False)
        ch.run()
        cls.f = list(ch.findings.values())

    def test_same_endpoints_as_java(self):
        java = build_contract(FIXTURE / "backend")
        self.assertEqual({(e["method"], e["path"]) for e in self.c["endpoints"]},
                         {(e["method"], e["path"]) for e in java["endpoints"]})
        ep = {(e["method"], e["path"]): e for e in self.c["endpoints"]}
        self.assertEqual(ep[("GET", "/api/orders")]["response"]["type"]["kind"], "page")
        self.assertEqual(ep[("GET", "/api/orders/{id}/receipt")]["response"]["format"], "text")
        self.assertEqual(ep[("DELETE", "/api/orders/{id}")]["response"]["format"], "none")
        self.assertEqual(ep[("DELETE", "/api/orders/{id}")]["pathParams"][0]["name"], "id")
        status = next(q for q in ep[("GET", "/api/orders")]["queryParams"] if q["name"] == "status")
        self.assertFalse(status["required"])  # OrderStatus? -> optional

    def test_kotlin_properties(self):
        props = {p["name"]: p for p in self.c["types"]["Order"]["properties"]}
        self.assertNotIn("internalNote", props)        # @field:JsonIgnore
        self.assertNotIn("auditTrail", props)          # private
        self.assertIn("itemCount", props)              # computed getter
        self.assertTrue(props["id"]["generated"])
        self.assertEqual(props["customerName"]["nonNullBecause"], "Kotlin non-null type")
        self.assertEqual(self.c["types"]["OrderStatus"]["values"], ["PENDING", "PAID", "SHIPPED", "CANCELLED"])
        req = {p["name"]: p for p in self.c["types"]["CreateOrderRequest"]["properties"]}
        self.assertEqual(list(req), ["customerName", "lines", "note"])
        self.assertTrue(req["note"]["nullable"])

    def test_same_errors_as_java(self):
        errors = sorted(f.code for f in self.f if f.severity == "error")
        self.assertEqual(errors, sorted(["endpoint-missing", "enum-mismatch", "field-not-sent", "field-not-sent",
                                         "method-mismatch", "page-vs-array", "text-as-json", "type-mismatch",
                                         "type-mismatch"]))
        self.assertTrue([f for f in self.f if f.code == "required-field-missing" and "lines" in f.message])


class AngularTest(unittest.TestCase):
    """HttpClient via constructor injection and inject(), class-field base URLs, environment prefixes."""

    @classmethod
    def setUpClass(cls):
        fe = TsProject(ROOT / "tests" / "fixtures" / "shop-app-angular" / "src", [], {})
        cls.calls = fe.calls
        ch = Checker(build_contract(FIXTURE / "backend"), fe, strict_nulls=False)
        ch.run()
        cls.f = [f for f in ch.findings.values() if f.severity != "info"]

    def test_calls_resolved(self):
        self.assertEqual(len(self.calls), 8)
        self.assertTrue(all(c.path for c in self.calls), [c.raw_url for c in self.calls if not c.path])
        self.assertTrue(all(c.client.startswith("angular:") for c in self.calls))

    def test_findings(self):
        got = sorted((f.code, (f.frontend or "").split(":")[-1]) for f in self.f)
        self.assertEqual(got, [("field-ignored", "39"), ("field-not-sent", "10"), ("method-mismatch", "43"),
                               ("page-vs-array", "31"), ("text-as-json", "47")])


class OpenApiTest(unittest.TestCase):
    """Non-Java backends via OpenAPI: a FastAPI-style 3.1 spec of the shop API, and Swagger 2.0."""

    @classmethod
    def setUpClass(cls):
        cls.oa = ROOT / "tests" / "fixtures" / "openapi"
        cls.contract = extract_openapi.load_any(cls.oa / "shop-fastapi.json")
        ch = Checker(cls.contract, TsProject(FIXTURE / "frontend" / "src", [], {}), strict_nulls=False)
        ch.run()
        cls.f = list(ch.findings.values())

    def has(self, code, needle):
        self.assertTrue([f for f in self.f if f.code == code and needle in f.message],
                        f"{code} {needle!r}:\n" + "\n".join(f"{f.code} {f.message}" for f in self.f))

    def test_same_bugs_found_through_openapi(self):
        self.has("field-not-sent", "customer_name")
        self.has("method-mismatch", "PATCH")
        self.has("endpoint-missing", "/cancel")
        self.has("text-as-json", "/receipt")
        self.has("type-mismatch", "Order.total")
        self.has("enum-mismatch", "REFUNDED")
        self.has("field-not-sent", "phone")
        self.has("type-mismatch", "OrderPage")            # array in TS, page object in the spec

    def test_contract_shape(self):
        eps = {(e["method"], e["path"]): e for e in self.contract["endpoints"]}
        self.assertEqual(eps[("DELETE", "/api/orders/{id}")]["response"]["format"], "none")
        self.assertEqual(eps[("GET", "/api/orders/{id}/receipt")]["response"]["format"], "text")
        self.assertEqual(eps[("GET", "/api/customers")]["response"]["type"]["kind"], "array")   # alias inlined
        self.assertNotIn("CustomerList", self.contract["types"])
        props = {p["name"]: p for p in self.contract["types"]["CreateOrderRequest"]["properties"]}
        self.assertTrue(props["note"]["optional"] and props["note"]["nullValue"])
        self.assertFalse(props["customerName"]["nullable"])

    def test_swagger2(self):
        c = extract_openapi.load_any(self.oa / "petstore-swagger2.json")
        eps = {(e["method"], e["path"]): e for e in c["endpoints"]}
        self.assertEqual(set(eps), {("GET", "/v1/pets"), ("POST", "/v1/pets"), ("DELETE", "/v1/pets/{petId}")})
        self.assertEqual(eps[("POST", "/v1/pets")]["body"]["type"], {"kind": "ref", "name": "Pet"})
        self.assertEqual(eps[("GET", "/v1/pets")]["response"]["type"]["kind"], "array")
        self.assertEqual(c["types"]["PetStatus"]["values"], ["available", "pending", "sold"])
        types = Gen(c).types_ts()
        self.assertIn("  id?: number;", types)
        self.assertIn("  name: string;", types)

    def test_rejects_unknown_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.json"
            p.write_text('{"hello": 1}', encoding="utf-8")
            with self.assertRaises(SystemExit):
                extract_openapi.load_any(p)


class GenerateTest(unittest.TestCase):
    def test_generated_output(self):
        g = Gen(build_contract(FIXTURE / "backend"))
        types, client = g.types_ts(), g.client_ts(None)
        self.assertIn('export type OrderStatus = "PENDING" | "PAID" | "SHIPPED" | "CANCELLED";', types)
        self.assertIn("export interface CreateOrderRequestInput", types)
        self.assertIn("total: number;", types)
        self.assertNotIn("internalNote", types)
        self.assertIn("export interface SpringPage<T>", types)
        self.assertIn("list: (query?: { status?: OrderStatus; page?: number; size?: number; sort?: string }", client)
        self.assertIn('receipt: (id: number, init?: RequestInit): Promise<string>', client)
        self.assertIn('response: "text"', client)
        # Reserved words are valid property names: orderApi.delete(id), not delete_.
        self.assertIn("  delete: (id: number", client)
        # Header names the backend folder only, so output is identical on every machine.
        self.assertIn("// Generated by api-contract-sync from backend/\n", types)
        self.assertNotIn(str(FIXTURE), types + client)


class CliTest(unittest.TestCase):
    """The CI-facing options: backend dir as input, --fail-on, annotations, generate --check."""

    def run_check(self, *extra):
        import contextlib
        import io
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = check_drift.main([str(FIXTURE / "backend"), str(FIXTURE / "frontend" / "src"),
                                     "--md", str(Path(tmp) / "r.md"), *extra])
        return code, out.getvalue()

    def test_backend_dir_and_exit_codes(self):
        self.assertEqual(self.run_check()[0], 1)                       # errors -> fail
        self.assertEqual(self.run_check("--fail-on", "never")[0], 0)
        self.assertEqual(self.run_check("--no-fail")[0], 0)

    def test_github_annotations(self):
        _, out = self.run_check("--github-annotations", "--no-fail")
        lines = [ln for ln in out.splitlines() if ln.startswith("::")]
        self.assertTrue(any(ln.startswith("::error file=") and "api/orders.ts" in ln and ",line=" in ln for ln in lines),
                        "\n".join(lines))
        self.assertTrue(all("\n" not in ln for ln in lines))

    def test_generate_check(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            args = [str(FIXTURE / "backend"), "-o", tmp]
            self.assertEqual(generate_ts.main(args + ["--check"]), 1)   # nothing generated yet
            self.assertEqual(generate_ts.main(args), 0)
            self.assertEqual(generate_ts.main(args + ["--check"]), 0)   # fresh
            p = Path(tmp) / "types.ts"
            p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
            self.assertEqual(generate_ts.main(args + ["--check"]), 0)   # CRLF checkout still counts as fresh
            p.write_text("// edited by hand\n", encoding="utf-8")
            self.assertEqual(generate_ts.main(args + ["--check"]), 1)   # stale


class UrlTest(unittest.TestCase):
    def test_normalize(self):
        P = PLACEHOLDER
        self.assertEqual(normalize_url(f"/api/x/{P}/y?z=1")[0], "/api/x/{}/y")
        self.assertEqual(normalize_url(f"/api/payments{P}")[0], "/api/payments")  # `${query}` suffix
        self.assertEqual(normalize_url("/customers", "/api")[0], "/api/customers")
        self.assertEqual(normalize_url("customers", "/api")[0], "/api/customers")
        self.assertEqual(normalize_url(f"{P}/customers"), ("/customers", True))
        self.assertEqual(normalize_url("http://localhost:8080/api/a")[0], "/api/a")


if __name__ == "__main__":
    unittest.main()
