# API Sentinel — Evidence-Based API Security, Two Modules

> **Prove API security failures before attackers do.**
> API Sentinel is a local-first developer-security tool suite with two additive modules:
>
> - **A. Authorization Sentinel** — detects **Broken Object-Level Authorization (BOLA/IDOR)** with
>   captured evidence and generated regression tests.
> - **B. API Sentinel Mesh · Trust Router** — a **local-first API trust gateway**: it evaluates a
>   primary API response for availability, latency, schema validity, freshness, required fields,
>   and prohibited-field policies; if the primary is unsafe or unreliable it routes to an approved
>   semantically compatible backup provider, normalizes the data into one stable response contract,
>   and produces an auditable explanation of the decision. Supported categories: **weather** and
>   **currency rates (FX)** — same policy engine, same trust score, same audit trail, proving the
>   gateway is provider-agnostic.
>
> **Providers serve real data by default** (free, keyless Open-Meteo weather + Frankfurter/ECB FX)
> with an honest live → cached → synthetic fallback chain. **100% keyless: no AI keys, no paid APIs,
> no cloud, no accounts, no database.** The scanner and the Trust Router engine itself never leave
> localhost; only the two provider-simulator modules fetch from the internet, and live data can be
> switched off entirely (`TRUST_ROUTER_LIVE_DATA=0` or `POST /data-mode {"data_mode":"synthetic"}`).

---

## 🧩 The Two Modules

### A. Authorization Sentinel — BOLA evidence & regression testing

Many APIs correctly verify that a user is logged in — but fail to verify whether that user is
*allowed* to access a specific resource.

- Alice is a logged-in customer who owns `order-1001`.
- Bob owns `order-1002`.
- If Alice changes her request from `GET /api/orders/order-1001` to
  `GET /api/orders/order-1002` … and the API returns Bob's private order with `200 OK`, the API
  has a critical authorization flaw: **BOLA / IDOR — API1:2023** in the OWASP API Security Top 10.

The scanner reads the target's OpenAPI contract, tests endpoints with simulated user roles, mutates
object identifiers, captures request/response evidence of unauthorized access, and generates pytest
regression tests that drop straight into CI.

### B. Trust Router — policy-aware fallback & response normalization

The scanner asks *“is this API safe to call?”* The Trust Router asks the complementary question:
*“can this response be trusted — and if not, what do we do instead?”*

For a requested category (**weather**, **FX rates**) it:

1. Calls the **primary provider** and measures latency.
2. Validates the raw response against a **provider-specific schema**.
3. Evaluates **policies**:

   | Policy | Value |
   |---|---|
   | `max_latency_ms` | **2000** |
   | `max_data_age_minutes` | **30** |
   | Required canonical fields | `location`, `temperature_c`, `condition`, `observed_at` |
   | Prohibited raw fields | `api_key`, `internal_user_id`, `customer_email` |

4. Computes an **explainable trust score 0–100** (schema 35 · policies 35 · freshness 15 ·
   availability 15) with a per-component breakdown and hard-gate verdict.
5. On any failure (status, latency, schema, freshness, required fields, or prohibited fields) it
   **selects the backup provider**, validates and normalizes its deliberately different JSON schema
   into the same canonical contract.
6. Returns the **final normalized response plus a decision timeline**; if *both* providers fail it
   returns a **safe degraded response** with no fabricated weather values and an explicit
   `unavailable: …` reason.

Canonical response contract (weather — flat, per MVP spec; other categories carry their values in a `metrics` map):

```json
{
  "location": "Bengaluru",
  "temperature_c": 27.5,
  "humidity_percent": 64,
  "condition": "Partly cloudy",
  "observed_at": "2026-09-19T12:03:30Z",
  "source": "backup:local-weather-backup-v1",
  "fallback_used": true,
  "trust_score": 100,
  "decision_reason": "primary rejected: freshness failed …; backup accepted (trust 100)"
}
```

FX responses normalize into the same envelope: `location` holds the pair (`USD/INR`) and the
rates live in `metrics` (`{"rate": 83.12, "inverse_rate": 0.012}`) — normalized from the backup
provider's deliberately different nested schema (`result.mid`, `result.rate_of_exchange`,
`result.as_of`).

---

## 🏗️ Architecture

Four local services, no cloud dependencies:

```text
┌────────────────────┐      ┌──────────────────────┐      ┌───────────────────────────┐
│ frontend (Vite)    │─────▶│ sentinel-engine      │─────▶│ provider-simulators :8002 │
│ React dashboard    │      │ FastAPI :8000        │      │ live-data providers       │
│ :5173              │      │ Module A: BOLA scan  │      │ /primary/…  (5 fault      │
│  Tab 1: Authorization│    │ Module B: Trust      │      │  modes per category)      │
│         Sentinel   │      │          Router      │      │ /backup/…    (nested      │
│  Tab 2: Trust Router│     │ (isolated packages:  │      │  different schemas)       │
└────────────────────┘      │  app/scanner vs      │      │ categories: weather + fx  │
                            │  app/trust_router)   │      └───────────────────────────┘
                            └──────────┬───────────┘
                                       │ (Module A only)
                            ┌──────────▼───────────────┐
                            │ vulnerable-demo-api :8001│
                            │ the BOLA demo scan target│
                            └──────────────────────────┘
```

| Service | Port | Purpose |
|---|---|---|
| `frontend/` | 5173 | Dark developer-tool dashboard with two tabs: **Authorization Sentinel** (scans, evidence, Verify Fix) and **Trust Router** (policy checks, score, timeline, fallback) |
| `sentinel-engine/` | 8000 | Module A: OpenAPI discovery, deterministic BOLA checks, findings, generated tests. Module B: Trust Router policy engine, normalizer, audit trail (`app/trust_router/`, import-isolated from the scanner) |
| `vulnerable-demo-api/` | 8001 | E-commerce demo API with **vulnerable**/**secure** modes — the BOLA scan target |
| `weather-providers/` | 8002 | Module B's provider simulators for **both categories** (weather + FX): per-category mode-switchable **primaries** (`healthy`, `slow_response`, `http_503`, `malformed_schema`, `stale_data`) and fixed healthy **backups** with deliberately different nested JSON schemas. Serve **real data by default** (live → cached → synthetic) from free keyless upstreams |

---

## 🌐 Live Real-World Data (providers)

The provider simulators on :8002 are **live by default** — the Trust Router demo runs on real
weather and real exchange rates with zero signup:

| Category | Upstream | Notes |
|---|---|---|
| weather | [Open-Meteo](https://open-meteo.com) geocoding + forecast APIs | free, keyless, no account |
| FX | [Frankfurter](https://frankfurter.dev) (ECB reference rates) | free, keyless, no account |

Every request resolves through the same **data-tier chain**, top-down, silently:

1. **live** — the upstream answered now; real observation/rate with a real `observed_at`
2. **cached** — a recent live answer reused (≤10 min TTL without re-fetching; ≤30 min served
   while the network is flaky, so the Trust Router's own freshness policy stays the honest judge)
3. **synthetic** — the deterministic local generator (offline fallback; the demo never breaks
   because the internet does)

The answering provider stamps every payload with a `data_source` marker (`live` / `cached` /
`synthetic`), which the Trust Router carries through its evidence and audit trail, and the
dashboard renders as a provenance badge (🌐 live · 🕒 cached · 🧪 synthetic).

**Controls**

```bash
# Per-request override
curl 'http://127.0.0.1:8002/primary/weather?city=Berlin&data_mode=synthetic'

# Service-wide, per category (weather | fx)
curl -X POST http://127.0.0.1:8002/data-mode -H 'Content-Type: application/json' \
     -d '{"data_mode": "synthetic", "category": "weather"}'

# Fully offline (env kill switch — CI default)
TRUST_ROUTER_LIVE_DATA=0 uvicorn app.main:app --port 8002
```

Only `weather-providers/app/live_weather.py` and `live_fx.py` may open outbound connections
(≤1.8 s budget, circuit-breaker after a failure, small in-memory caches). The vulnerable demo
API, the scanner engine, and the Trust Router itself remain 100% loopback-only.

**Trust Router endpoints**

| Endpoint | Purpose |
|---|---|
| `GET /trust-router/providers` | Catalog of approved local providers and primary fault modes |
| `POST /trust-router/request` | `{"city": "Bengaluru"}` → normalized response + policy checks + score + timeline |
| `POST /trust-router/primary-mode` | `{"mode": "stale_data"}` → switch the primary simulator's fault mode |
| `GET /trust-router/primary-mode?category=…` | Read a category's current primary fault mode (dashboard state sync) |
| `GET /trust-router/audit/{request_id}` | The full stored decision record for one request |

The gateway is **category-agnostic**: each category is one `CategorySpec` entry in
`app/trust_router/registry.py` (schemas, normalizer, canonical builder, pinned env-var names),
and the policy engine, scorer, orchestrator, and audit trail are shared. FX fault modes are
independent of weather modes (`POST /trust-router/primary-mode` takes a `category`).

**Isolation by design:** `app/trust_router/` imports only stdlib + httpx + pydantic + fastapi —
never `app.scanner`/`app.store`/`app.models` (enforced by `tests/test_module_isolation.py`). It has
its own ID space (`tr-req-…`), its own in-memory audit store, its own loopback-only URL guard, and
provider URLs are pinned server-side; API clients can never point it at a remote host. All external
calls have hard timeouts (connect 1.5 s / read 2.0 s) and degrade gracefully into fallback.

---

## 🎬 Demo Walkthroughs

### The Hero Demo — Authorization Sentinel (BOLA)

1. Start all services (commands below) and open the dashboard's **Authorization Sentinel** tab.
2. The demo API is in **Vulnerable** mode. Click **Run Authorization Scan**:
   - Scanner loads the target's OpenAPI contract.
   - Alice's own order returns `200 OK` ✔ (baseline)
   - Alice requests **Bob's** order → API returns **`200 OK` with Bob's private data** ✘
   - Scanner creates a **Critical** BOLA finding with request/response evidence and a generated
     pytest regression test.
3. Click **Switch to Secure Mode**, then **Verify Fix**:
   - Alice requesting Bob's order now gets **`403 Forbidden`** ✔
   - The finding flips to **passed** — regression test green.

### The Trust Router Demo — policy-aware fallback

1. Open the **Trust Router** tab. Providers answer **live by default** — real Open-Meteo weather
   and real ECB/Frankfurter rates, with a 🌐 LIVE badge on the response (they silently fall back
   to cached/synthetic data offline, shown as 🕒/🧪).
2. Primary mode **`healthy`** → click **Get Trusted Weather**:
   - All six policy checks pass ✓, trust score **100**, banner reads **PRIMARY USED**.
3. Switch the primary provider mode to **`stale_data`** and run again:
   - Freshness check fails: *“observed_at is 90 min old (> 30 min budget)”* — primary score 85 but
     the hard gate failed; the router selects the backup, normalizes its nested schema, banner reads
     **FALLBACK USED**, and the decision timeline shows every step with timestamps.
4. Try **`http_503`**, **`slow_response`** (times out past the 2000 ms budget), and
   **`malformed_schema`** (missing field + leaked `internal_user_id`) — each ends in an auditable
   fallback with the failing check called out.
5. Switch to the **Currency rates (FX)** category (💱), pick a pair like `USD/INR`, and repeat:
   same policy checks, same trust-score panel, same fallback behavior — but a completely different
   provider schema and canonical shape (`rate`, `inverse_rate` in `metrics`). Set the **FX**
   primary to `malformed_schema` to see it leak `customer_email`, fail the prohibited-field gate,
   and fall back to the FX backup's nested `result.*` schema.
6. For the **safe degraded** state, stop the provider-simulators service and run a request in
   either category: both calls fail, and the response contains **no fabricated values** — only an
   explicit `unavailable: …` reason.
7. Every run is auditable afterwards:

   ```bash
   curl -s http://127.0.0.1:8000/trust-router/audit/tr-req-0001 | python3 -m json.tool
   ```

---

## 👤 Demo Data (synthetic)

**Users**

| Name | ID | Role | Token |
|---|---|---|---|
| Alice | `user-101` | customer | `alice-token` |
| Bob | `user-102` | customer | `bob-token` |
| Priya | `admin-001` | admin | `admin-token` |

**Orders**

| Order | Owner | Items | Total | Shipping address |
|---|---|---|---|---|
| `order-1001` | Alice (`user-101`) | Wireless Keyboard, USB-C Hub | 79.98 | 18 Lake View Road |
| `order-1002` | Bob (`user-102`) | Noise-Cancelling Headphones | 149.99 | 42 Park Street |

**Weather cities (synthetic)**: Bengaluru (27.5 °C, partly cloudy), London, New York, Singapore,
Tokyo, Sydney — plus deterministic synthesized values for any other city string.

**FX pairs (synthetic)**: USD/INR (83.12), USD/EUR (0.9134), USD/GBP, USD/JPY, USD/SGD, USD/AUD —
plus deterministic synthesized rates for any other pair. FX fault modes are controlled separately
from weather modes.

**Hero request (Module A)**

```http
GET /api/orders/order-1002
Authorization: Bearer alice-token
```

- Vulnerable mode → `200 OK` with Bob's order incl. `shipping_address`
- Secure mode → `403 Forbidden`
- Priya (admin) → `200 OK` in secure mode (admins may access all orders)

---

## 🛡️ Security & Ethics Constraints

This is an **educational tool for a controlled local environment**:

- Both modules **only** talk to local services: `localhost`, `127.0.0.1`, `::1`, `*.localhost`,
  private LAN ranges, and this project's Docker service hostnames. Arbitrary public URLs are
  rejected (Module A by `app/target_guard.py`, Module B by its own loopback guard).
- **No stealth, brute force, bypasses, exploitation, or public scanning.** The only technique in
  Module A is a deterministic own-resource vs. cross-resource comparison using synthetic data.
- `Authorization` headers are **redacted** in every frontend-visible response.
- The Trust Router never stores raw provider bodies in its audit trail — only field **names**, with
  prohibited ones listed under `raw_fields_redacted` (the short `data_source` provenance marker is
  the only value carried through, deliberately).
- Demo/BOLA data (users, orders, tokens) is synthetic. Provider data is **live by default** from
  the free keyless Open-Meteo and Frankfurter upstreams — no API keys, no accounts, no paid
  services. Only the two provider-simulator modules may leave localhost; the scanner and Trust
  Router engine never do. Live data can be disabled at any time with the
  `TRUST_ROUTER_LIVE_DATA=0` env kill switch or `POST /data-mode {"data_mode":"synthetic"}`.
  No production data, real credentials, AI APIs, cloud deployment, user accounts, or database.

---

## ▶️ Run Plan (local, no Docker)

Prerequisites: **Python 3.11+**, **Node 18+**, `pip`, `npm`.

**One-command demo launcher (recommended for the live demo):**

```bash
./run_all.sh                    # starts all four services, waits for health, resets demo mode
./run_all.sh --keep-mode        # same, but leaves the demo API's current mode untouched
scripts/dev_daemon.sh start     # alternative: detached background services (logs in .run/)
scripts/dev_daemon.sh status    # or: stop
```

Logs go to `.run/*.log`; `Ctrl+C` stops everything `run_all.sh` started.

**Manual per-service startup:**

```bash
# 1) Target demo API — port 8001 (Module A)
cd vulnerable-demo-api
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --port 8001

# 2) Scanner engine — port 8000 (Modules A + B)
cd sentinel-engine
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --port 8000

# 3) Weather providers — port 8002 (Module B)
cd weather-providers
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --port 8002

# 4) Dashboard — port 5173
cd frontend
npm install
npm run dev
```

Then open **http://localhost:5173**.

**Backend tests**

```bash
cd vulnerable-demo-api && venv/bin/python -m pytest -v   # Module A target API
cd sentinel-engine    && venv/bin/python -m pytest -v    # Modules A + B (incl. Trust Router & isolation tests)
cd weather-providers  && venv/bin/python -m pytest -v    # Module B provider simulators
```

**Quick Trust Router smoke (no UI):**

```bash
curl -s http://127.0.0.1:8000/trust-router/providers | python3 -m json.tool
curl -s -X POST http://127.0.0.1:8000/trust-router/primary-mode \
     -H 'Content-Type: application/json' -d '{"mode":"stale_data"}'
curl -s -X POST http://127.0.0.1:8000/trust-router/request \
     -H 'Content-Type: application/json' -d '{"city":"Bengaluru"}' | python3 -m json.tool

# FX category (same gateway, different providers + schema):
curl -s -X POST http://127.0.0.1:8000/trust-router/primary-mode \
     -H 'Content-Type: application/json' -d '{"mode":"stale_data","category":"fx"}'
curl -s -X POST http://127.0.0.1:8000/trust-router/request \
     -H 'Content-Type: application/json' -d '{"location":"USD/INR","category":"fx"}' | python3 -m json.tool
```

Docker Compose (`docker compose up --build`) arrives in Phase 5.

---

## 📊 Status

Phased build with acceptance gates — see [TASKS.md](TASKS.md) for the live checklist.

| Phase | Scope | Status |
|---|---|---|
| 0 | Repo scaffold + plan | ✅ Done |
| 1 | Vulnerable demo API + tests | ✅ Done |
| 2 | Sentinel scanner engine (Module A) | ✅ Done |
| 3 | Basic dashboard | ✅ Done |
| 3M | **API Sentinel Mesh: Trust Router (Module B)** — providers, policy engine, fallback, audit | ✅ Done |
| 3L | **Live real-world provider data** — Open-Meteo + Frankfurter, live → cached → synthetic, provenance end-to-end | ✅ Done |
| 4 | Presentation-ready finding details | ⬜ Next |
| 5 | Polish, Docker Compose, demo script | ⬜ Planned |
| 6 | Optional AI explanation (opt-in only) | ⬜ Blocked until approved |
