"""Build tests/fixtures/erp-app: a 16-controller Spring + React fixture with subtle drift.

Run from anywhere: python tests/fixtures/build_erp_app.py  (overwrites erp-app/).

The answer key lives here, not in the generated files, so eval runs that only see
erp-app/ get no hints.

Planted drift (frontend is wrong):
  B1  products.ts   `sku`        backend @JsonProperty("sku_code")
  B2  products.ts   `isActive`   Lombok `boolean isActive` serializes as `active`
  B3  suppliers.ts  `email`      backend field is `contactEmail`
  B4  invoices.ts   total: string            BigDecimal -> JSON number
  B5  invoices.ts   print() uses .json()     endpoint returns String (text/plain)
  B6  payments.ts   'BANK'                   enum is BANK_TRANSFER
  B7  refunds.ts    amount: string           BigDecimal -> JSON number
  B8  stock.ts      list typed as array      endpoint returns Page<StockMovement>
  B9  purchaseOrders.ts  POST /{id}/approve  endpoint is /{id}/approval
  B10 employees.ts  passwordHash: string     @JsonIgnore, never sent
  B11 shifts.ts     close() uses POST        endpoint is PUT /{id}/close
  B12 coupons.ts    create sends `expiry`    request record field is `expiresAt`

Decoys (look suspicious, are correct):
  D1  deliveries.ts `tracking_no`  backend @JsonProperty("tracking_no")
  D2  discounts.ts  `active`       Lombok `boolean active` -> `active`
  D3  payments.ts   amount: number (BigDecimal, correct)
  D4  taxRates.ts   rate: number   (BigDecimal, correct)
"""

from __future__ import annotations

import shutil
from pathlib import Path

OUT = Path(__file__).resolve().parent / "erp-app"
PKG = "com.acme.erp"
JAVA = OUT / "backend" / "src" / "main" / "java" / "com" / "acme" / "erp"
TS = OUT / "frontend" / "src" / "api"

# field: (java type, java name, java annotations, ts name or None to omit, ts type)
D = {
    "Product": dict(path="products", style="axios", fields=[
        ("String", "name", "@Column(nullable = false)", "name", "string"),
        ("String", "sku", '@JsonProperty("sku_code")', "sku", "string"),               # B1
        ("BigDecimal", "price", "", "price", "number"),
        ("boolean", "isActive", "", "isActive", "boolean"),                           # B2
        ("Long", "categoryId", "", "categoryId", "number"),
        ("int", "stock", "", "stock", "number"),
    ]),
    "Category": dict(path="categories", style="axios", fields=[
        ("String", "name", "", "name", "string"),
        ("Long", "parentId", "", "parentId", "number | null"),
    ]),
    "Supplier": dict(path="suppliers", style="fetch", fields=[
        ("String", "name", "", "name", "string"),
        ("String", "contactEmail", "", "email", "string"),                             # B3
        ("String", "phone", "", "phone", "string"),
    ]),
    "Customer": dict(path="customers", style="axios", fields=[
        ("String", "fullName", "", "fullName", "string"),
        ("String", "email", "", "email", "string"),
        ("String", "phone", "", "phone", "string"),
        ("int", "loyaltyPoints", "", "loyaltyPoints", "number"),
    ]),
    "Invoice": dict(path="invoices", style="fetch", fields=[
        ("String", "number", "", "number", "string"),
        ("Long", "customerId", "", "customerId", "number"),
        ("BigDecimal", "total", "", "total", "string"),                                # B4
        ("InvoiceStatus", "status", "", "status", "InvoiceStatus"),
        ("LocalDateTime", "issuedAt", "", "issuedAt", "string"),
    ]),
    "Payment": dict(path="payments", style="axios", fields=[
        ("Long", "invoiceId", "", "invoiceId", "number"),
        ("BigDecimal", "amount", "", "amount", "number"),                              # D3
        ("PaymentMethod", "method", "", "method", "PaymentMethod"),
        ("LocalDateTime", "paidAt", "", "paidAt", "string"),
    ]),
    "Refund": dict(path="refunds", style="fetch", fields=[
        ("Long", "paymentId", "", "paymentId", "number"),
        ("BigDecimal", "amount", "", "amount", "string"),                              # B7
        ("String", "reason", "", "reason", "string"),
    ]),
    "Warehouse": dict(path="warehouses", style="axios", fields=[
        ("String", "name", "", "name", "string"),
        ("String", "location", "", "location", "string"),
    ]),
    "StockMovement": dict(path="stock-movements", style="fetch", file="stock", paged=True, fields=[
        ("Long", "productId", "", "productId", "number"),
        ("Long", "warehouseId", "", "warehouseId", "number"),
        ("int", "quantity", "", "quantity", "number"),
        ("LocalDateTime", "movedAt", "", "movedAt", "string"),
    ]),
    "PurchaseOrder": dict(path="purchase-orders", style="axios", fields=[
        ("Long", "supplierId", "", "supplierId", "number"),
        ("BigDecimal", "total", "", "total", "number"),
        ("PoStatus", "status", "", "status", "PoStatus"),
    ]),
    "Employee": dict(path="employees", style="fetch", fields=[
        ("String", "fullName", "", "fullName", "string"),
        ("Role", "role", "", "role", "Role"),
        ("String", "passwordHash", "@JsonIgnore", "passwordHash", "string"),          # B10
    ]),
    "Shift": dict(path="shifts", style="axios", fields=[
        ("Long", "employeeId", "", "employeeId", "number"),
        ("LocalDateTime", "openedAt", "", "openedAt", "string"),
        ("LocalDateTime", "closedAt", "", "closedAt", "string | null"),
    ]),
    "Discount": dict(path="discounts", style="fetch", fields=[
        ("String", "name", "", "name", "string"),
        ("BigDecimal", "percent", "", "percent", "number"),
        ("boolean", "active", "", "active", "boolean"),                               # D2
    ]),
    "Coupon": dict(path="coupons", style="axios", create_record=True, fields=[
        ("String", "code", "", "code", "string"),
        ("LocalDate", "expiresAt", "", "expiresAt", "string"),
    ]),
    "Delivery": dict(path="deliveries", style="fetch", fields=[
        ("Long", "invoiceId", "", "invoiceId", "number"),
        ("String", "trackingNumber", '@JsonProperty("tracking_no")', "tracking_no", "string"),  # D1
        ("String", "carrier", "", "carrier", "string"),
    ]),
    "TaxRate": dict(path="tax-rates", style="axios", file="taxRates", fields=[
        ("String", "name", "", "name", "string"),
        ("BigDecimal", "rate", "", "rate", "number"),                                  # D4
    ]),
}

ENUMS = {
    "InvoiceStatus": (["DRAFT", "ISSUED", "PAID", "VOID"], ["DRAFT", "ISSUED", "PAID", "VOID"]),
    "PaymentMethod": (["CASH", "CARD", "BANK_TRANSFER", "MOBILE_WALLET"], ["CASH", "CARD", "BANK", "MOBILE_WALLET"]),  # B6
    "PoStatus": (["OPEN", "APPROVED", "RECEIVED", "CANCELLED"], ["OPEN", "APPROVED", "RECEIVED", "CANCELLED"]),
    "Role": (["OWNER", "MANAGER", "CASHIER"], ["OWNER", "MANAGER", "CASHIER"]),
}
ENUM_HOME = {"InvoiceStatus": "invoices", "PaymentMethod": "payments", "PoStatus": "purchaseOrders", "Role": "employees"}


def lower_first(s):
    return s[0].lower() + s[1:]


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.lstrip("\n"), encoding="utf-8", newline="\n")


def entity(name, spec):
    body = []
    for jt, jn, ann, _, _ in spec["fields"]:
        if ann:
            body.append(f"    {ann}")
        body.append(f"    private {jt} {jn};")
        body.append("")
    return f"""
package {PKG}.model;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.persistence.*;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import lombok.Data;

@Data
@Entity
public class {name} {{

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

{chr(10).join(body).rstrip()}
}}
"""


def controller(name, spec):
    var = lower_first(name)
    repo = f"{name}Repository"
    extra, imports = [], set()
    if spec.get("paged"):
        list_m = f"""    @GetMapping
    public Page<{name}> list(Pageable pageable) {{
        return repository.findAll(pageable);
    }}"""
        imports |= {"org.springframework.data.domain.Page", "org.springframework.data.domain.Pageable"}
    else:
        list_m = f"""    @GetMapping
    public List<{name}> list() {{
        return repository.findAll();
    }}"""
    create_body = f"@RequestBody {name} {var}"
    create_impl = f"return repository.save({var});"
    if spec.get("create_record"):
        create_body = f"@Valid @RequestBody Create{name}Request request"
        create_impl = f"{name} {var} = new {name}();\n        {var}.setCode(request.code());\n        {var}.setExpiresAt(request.expiresAt());\n        return repository.save({var});"
        extra.append(f"    public record Create{name}Request(@NotBlank String code, @NotNull LocalDate expiresAt) {{ }}")
        imports |= {"jakarta.validation.Valid", "jakarta.validation.constraints.NotBlank",
                    "jakarta.validation.constraints.NotNull", "java.time.LocalDate"}
    if name == "Invoice":
        extra.append("""    /** Plain-text invoice for the receipt printer. */
    @GetMapping("/{id}/print")
    public String print(@PathVariable Long id) {
        return repository.findById(id).map(InvoiceText::render).orElseThrow();
    }""")
    if name == "PurchaseOrder":
        extra.append("""    @PostMapping("/{id}/approval")
    public PurchaseOrder approve(@PathVariable Long id) {
        PurchaseOrder po = repository.findById(id).orElseThrow();
        po.setStatus(PoStatus.APPROVED);
        return repository.save(po);
    }""")
        imports.add(f"{PKG}.model.PoStatus")
    if name == "Shift":
        extra.append("""    @PutMapping("/{id}/close")
    public Shift close(@PathVariable Long id) {
        Shift shift = repository.findById(id).orElseThrow();
        shift.setClosedAt(LocalDateTime.now());
        return repository.save(shift);
    }""")
        imports.add("java.time.LocalDateTime")
    imp = "\n".join(f"import {i};" for i in sorted(imports | {
        f"{PKG}.model.{name}", f"{PKG}.repository.{repo}", "java.util.List", "lombok.RequiredArgsConstructor",
        "org.springframework.http.HttpStatus", "org.springframework.web.bind.annotation.*"}))
    extras = ("\n\n" + "\n\n".join(extra)) if extra else ""
    return f"""
package {PKG}.controller;

{imp}

@RestController
@RequestMapping("/api/{spec['path']}")
@RequiredArgsConstructor
public class {name}Controller {{

    private final {repo} repository;

{list_m}

    @GetMapping("/{{id}}")
    public {name} get(@PathVariable Long id) {{
        return repository.findById(id).orElseThrow();
    }}

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public {name} create({create_body}) {{
        {create_impl}
    }}

    @PutMapping("/{{id}}")
    public {name} update(@PathVariable Long id, @RequestBody {name} {var}) {{
        {var}.setId(id);
        return repository.save({var});
    }}

    @DeleteMapping("/{{id}}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable Long id) {{
        repository.deleteById(id);
    }}{extras}
}}
"""


def ts_interface(name, spec):
    lines = [f"export interface {name} {{", "  id: number;"]
    lines += [f"  {tn}: {tt};" for _, _, _, tn, tt in spec["fields"] if tn]
    return "\n".join(lines + ["}"])


def ts_enums(fname):
    out = []
    for en, (_, ts_vals) in ENUMS.items():
        if ENUM_HOME[en] == fname:
            out.append(f"export type {en} = " + " | ".join(f"'{v}'" for v in ts_vals) + ";")
    return ("\n".join(out) + "\n\n") if out else ""


def ts_axios(name, spec, fname):
    p, api = spec["path"], f"{lower_first(name)}Api"
    imports = ""
    head = f"import {{ http }} from './http';\n{imports}\n"
    extra = ""
    create_t = f"Omit<{name}, 'id'>"
    if name == "Coupon":
        head += "export interface NewCoupon {\n  code: string;\n  expiry: string;\n}\n\n"          # B12
        create_t = "NewCoupon"
    if name == "PurchaseOrder":
        extra = f"  approve: (id: number) => http.post<{name}>(`/{p}/${{id}}/approve`).then((r) => r.data),\n"  # B9
    if name == "Shift":
        extra = f"  close: (id: number) => http.post<{name}>(`/{p}/${{id}}/close`).then((r) => r.data),\n"     # B11
    return f"""{head}{ts_enums(fname)}{ts_interface(name, spec)}

export const {api} = {{
  list: () => http.get<{name}[]>('/{p}').then((r) => r.data),
  get: (id: number) => http.get<{name}>(`/{p}/${{id}}`).then((r) => r.data),
  create: (body: {create_t}) => http.post<{name}>('/{p}', body).then((r) => r.data),
  update: (id: number, body: Omit<{name}, 'id'>) => http.put<{name}>(`/{p}/${{id}}`, body).then((r) => r.data),
  remove: (id: number) => http.delete(`/{p}/${{id}}`),
{extra}}};
"""


def ts_fetch(name, spec, fname):
    p = spec["path"]
    plural = name + ("s" if not name.endswith("y") else "")
    plural = {"Delivery": "Deliveries", "StockMovement": "StockMovements"}.get(name, plural)
    list_t = f"{name}[]"
    extra = ""
    if name == "Invoice":
        extra = f"""
export async function printInvoice(id: number): Promise<{{ text: string }}> {{
  const res = await fetch(`${{BASE}}/${{id}}/print`, {{ credentials: 'include' }});
  return (await res.json()) as {{ text: string }};
}}
"""                                                                                                   # B5
    return f"""{ts_enums(fname)}{ts_interface(name, spec)}

const BASE = '/api/{p}';

async function send<T>(url: string, init: RequestInit = {{}}): Promise<T> {{
  const res = await fetch(url, {{ credentials: 'include', headers: {{ 'Content-Type': 'application/json' }}, ...init }});
  if (!res.ok) {{
    const problem = (await res.json()) as {{ message?: string }};
    throw new Error(problem.message ?? res.statusText);
  }}
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}}

export async function list{plural}(): Promise<{list_t}> {{
  const res = await fetch(BASE, {{ credentials: 'include' }});
  return (await res.json()) as {list_t};
}}

export async function get{name}(id: number): Promise<{name}> {{
  const res = await fetch(`${{BASE}}/${{id}}`, {{ credentials: 'include' }});
  return (await res.json()) as {name};
}}

export async function create{name}(body: Omit<{name}, 'id'>): Promise<{name}> {{
  const res = await fetch(BASE, {{
    method: 'POST',
    credentials: 'include',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify(body),
  }});
  return (await res.json()) as {name};
}}

export async function update{name}(id: number, body: Omit<{name}, 'id'>): Promise<{name}> {{
  const res = await fetch(`${{BASE}}/${{id}}`, {{
    method: 'PUT',
    credentials: 'include',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify(body),
  }});
  return (await res.json()) as {name};
}}

export async function delete{name}(id: number): Promise<void> {{
  await fetch(`${{BASE}}/${{id}}`, {{ method: 'DELETE', credentials: 'include' }});
}}
{extra}"""


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    write(OUT / "backend" / "pom.xml", """
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.3.4</version>
  </parent>
  <groupId>com.acme</groupId>
  <artifactId>erp</artifactId>
  <version>0.1.0</version>
  <dependencies>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId></dependency>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-data-jpa</artifactId></dependency>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-validation</artifactId></dependency>
    <dependency><groupId>org.projectlombok</groupId><artifactId>lombok</artifactId><optional>true</optional></dependency>
  </dependencies>
</project>
""")
    write(OUT / "backend" / "src" / "main" / "resources" / "application.properties",
          "spring.application.name=erp\nspring.jpa.open-in-view=false\n")
    write(JAVA / "ErpApplication.java", f"""
package {PKG};

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class ErpApplication {{
    public static void main(String[] args) {{
        SpringApplication.run(ErpApplication.class, args);
    }}
}}
""")
    for en, (java_vals, _) in ENUMS.items():
        write(JAVA / "model" / f"{en}.java", f"package {PKG}.model;\n\npublic enum {en} {{\n    "
              + ",\n    ".join(java_vals) + "\n}\n")
    for name, spec in D.items():
        write(JAVA / "model" / f"{name}.java", entity(name, spec))
        write(JAVA / "repository" / f"{name}Repository.java", f"""
package {PKG}.repository;

import {PKG}.model.{name};
import org.springframework.data.jpa.repository.JpaRepository;

public interface {name}Repository extends JpaRepository<{name}, Long> {{ }}
""")
        write(JAVA / "controller" / f"{name}Controller.java", controller(name, spec))
    write(JAVA / "controller" / "InvoiceText.java", f"""
package {PKG}.controller;

import {PKG}.model.Invoice;

final class InvoiceText {{
    private InvoiceText() {{ }}

    static String render(Invoice invoice) {{
        return "INVOICE " + invoice.getNumber() + "\\nTOTAL " + invoice.getTotal();
    }}
}}
""")

    write(OUT / "frontend" / "package.json", """
{
  "name": "erp-frontend",
  "private": true,
  "type": "module",
  "scripts": { "dev": "vite", "build": "tsc -b && vite build" },
  "dependencies": { "axios": "^1.7.7", "react": "^18.3.1", "react-dom": "^18.3.1" },
  "devDependencies": { "typescript": "^5.6.3", "vite": "^5.4.10" }
}
""")
    write(TS / "http.ts", """
import axios from 'axios';

export const http = axios.create({
  baseURL: '/api',
  withCredentials: true,
});
""")
    files = {}
    for name, spec in D.items():
        fname = spec.get("file") or {
            "purchase-orders": "purchaseOrders", "stock-movements": "stock", "tax-rates": "taxRates",
        }.get(spec["path"], spec["path"])
        files[name] = fname
        # B8 needs no special case: every list is typed as an array, but StockMovement's is a Page.
        src = ts_axios(name, spec, fname) if spec["style"] == "axios" else ts_fetch(name, spec, fname)
        write(TS / f"{fname}.ts", src)
    print(f"Wrote {OUT} ({len(D)} controllers)")


if __name__ == "__main__":
    main()
