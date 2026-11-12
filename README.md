# api-contract-sync

Catch the bugs that happen when a backend and a JavaScript/TypeScript frontend
disagree about the API, before they reach users. It also generates a typed fetch
client from the backend.

```text
$ api-contract-sync check backend frontend/src
## Errors
- [field-not-sent] `Product.sku` does not exist on backend type Product; it is always undefined at runtime
  Frontend `api/products.ts:6` · Backend `com/acme/erp/model/Product.java:13`
  hint: the Java field `sku` is sent as `sku_code` (@JsonProperty); use `sku_code`
- [method-mismatch] POST /api/shifts/{}/close: backend only accepts PUT on /api/shifts/{id}/close
- [page-vs-array] `StockMovement[]` is an array in TS but the backend returns a Spring Page (items are under `.content`)
- [type-mismatch] `Invoice.total` is `string` in TS but `number (decimal)` in the backend
...
drift: 12 errors, 9 warnings
```

It has no dependencies and runs on Python 3.10+. For Spring Boot it reads the source
code directly; it doesn't need a running backend, a Java toolchain or Node.

## Supported stacks

| Backend | How |
|---|---|
| **Spring Boot — Java or Kotlin** | Reads the source directly, with Jackson's rules (Lombok, records, data classes, `@JsonProperty`, `@JsonIgnore`, `Page`, ...) |
| **Anything that exports OpenAPI / Swagger** — FastAPI, Django REST, NestJS, Express (with swagger), ASP.NET, Go, Laravel, Rails, Spring (springdoc) | Pass the `openapi.json` (OpenAPI 3.0 / 3.1, Swagger 2.0; YAML with `pip install pyyaml`) |

| Frontend | Notes |
|---|---|
| TypeScript (`.ts`, `.tsx`) — React, Next.js, Vue, Svelte, Angular | Full checks, including response and body types |
| JavaScript (`.js`, `.jsx`, `.mjs`) | URL, verb, text-vs-JSON and body-field checks (no types to compare) |
| `.vue` and `.svelte` files | The `<script>` blocks are read |
| HTTP clients | `fetch`, `axios` and `axios.create()` instances, Angular `HttpClient`, and your own wrappers via `--client-fn` |

The generated client is TypeScript.

## Install

```bash
pip install api-contract-sync
```

## Commands

| Command | What it does |
|---|---|
| `api-contract-sync check <backend> <frontend/src>` | Reports drift. Exits 1 on errors. |
| `api-contract-sync check openapi.json <frontend/src>` | The same, for any backend that exports OpenAPI. |
| `api-contract-sync generate <backend or openapi.json> -o <dir>` | Writes `types.ts`, `client.ts` and `index.ts`. |
| `api-contract-sync generate <backend or openapi.json> -o <dir> --check` | Exits 1 if the committed client is stale. |
| `api-contract-sync extract <backend or openapi.json> -o contract.json` | Writes the intermediate contract, for tooling. |

Useful `check` options:
- `--md report.md` / `--json report.json`
- `--fail-on error|warning|never`
- `--github-annotations`
- `--client-fn apiFetch:/api`, for custom fetch wrappers
- `--exclude src/api/generated`
- `--strict-nulls`
- `--context-path`, `--bigdecimal string` and `--naming snake`, if Jackson or Spring is configured in Java code instead of `application.properties`

## What it catches

| Finding | Example |
|---|---|
| Renamed or removed fields | TS `customer_name`, but Jackson sends `customerName` |
| Jackson naming rules | `@JsonProperty("sku_code")`; Lombok `boolean isActive` sent as `active`; `@JsonIgnore`; read-only and write-only fields |
| Wrong scalar types | `BigDecimal` arrives as a JSON number, but TS says `string`; `LocalDateTime` arrives as a string, but TS says `Date` |
| Wrong shapes | A Spring `Page<T>` read as `T[]`; a `String` response parsed with `.json()`; casting a `void` response |
| Endpoints | Unknown paths (with the closest real ones), wrong HTTP verbs, body sent to an endpoint that ignores it |
| Enums | TS literal values the Java enum doesn't have; Java values the TS union misses |
| Request bodies | Fields the backend ignores; `@NotNull` fields never sent |

The frontend side resolves URLs through template literals, constants, class fields
(`${this.apiUrl}/orders`) and concatenation, and reads the response type from generics,
casts, annotations and return types. The Spring side understands Spring MVC
annotations, records, Kotlin data classes and nullability, Lombok, inheritance,
generics, `ResponseEntity`/`Optional`/`Page`, validation annotations and
`application.properties`/`yml`.

**Limits:** For non-Spring backends, results are only as accurate as the OpenAPI
document. Spring WebFlux functional routes, custom Jackson serializers, `@JsonView`
and mixins aren't modelled. URLs built at runtime from unknown values are listed as
unresolved, not guessed.

## GitHub Actions

```yaml
- uses: actions/checkout@v7
- uses: krishanSKDA/api-contract-sync@v0.1.0
  with:
    backend: backend
    frontend: frontend/src
    generated-dir: frontend/src/api/generated   # optional: also fail on a stale generated client
```

Findings appear as annotations on the pull request diff, and the full report is added
to the job summary. See [examples/api-drift.yml](examples/api-drift.yml).

## The generated client

```ts
import { orderApi, configureApi, ApiError, type CreateOrderRequestInput } from './api/generated';

configureApi({ baseUrl: '/api-host', headers: () => ({ Authorization: `Bearer ${token()}` }) });

const order = await orderApi.create({ customerName: 'Ada', lines: [{ sku: 'A-1', quantity: 2 }] });
const page = await orderApi.list({ status: 'PENDING', page: 0, size: 20 });   // SpringPage<Order>
const text = await orderApi.receipt(order.id);                                  // string (text/plain)
```

- Each DTO, record, data class, entity or OpenAPI schema becomes an interface. Each enum becomes a union type plus a `XxxValues` array.
- Types used as request bodies also get an `XxxInput` variant, where generated ids are optional and read-only fields are left out.
- The client uses `fetch`, has no runtime dependencies, and sends `credentials: 'include'`, so Spring session cookies keep working.

## Python API

```python
from api_contract_sync import build_contract, check, render_client

contract = build_contract("backend")
for f in check(contract, "frontend/src"):
    print(f.severity, f.code, f.message, f.frontend, f.hint)
files = render_client(contract)   # {"types.ts": "...", "client.ts": "...", "index.ts": "..."}
```

## Development

```bash
python -m unittest discover -s tests          # 31 tests against the fixtures in tests/fixtures
python tools/sync_skill.py <skill-dir>        # copy modules into the Claude Code skill
```

The same modules also power an `api-contract-sync` Claude Code skill. It runs them as
plain scripts, which is why every module falls back to flat imports.
