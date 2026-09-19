# API Sentinel — Evidence-Based API Authorization Testing

> **Prove API authorization failures before attackers do.**

API Sentinel is a local-first developer-security tool that detects **Broken Object-Level
Authorization (BOLA / IDOR)** in REST APIs. It reads an API's OpenAPI contract, tests endpoints
with simulated user roles, mutates object identifiers, captures evidence of unauthorized access,
and generates regression tests developers can drop straight into their CI pipeline.

**100% local. 100% deterministic. No AI keys required.**

---

## 🚨 The Problem

Many APIs correctly verify that a user is logged in — but fail to verify whether that user is
*allowed* to access a specific resource.

- Alice is a logged-in customer who owns `order-1001`.
- Bob owns `order-1002`.
- If Alice changes her request from:

```text
GET /api/orders/order-1001
```

to:

```text
GET /api/orders/order-1002
```

…and the API returns Bob's private order with `200 OK`, the API has a critical authorization flaw.
This is **Broken Object-Level Authorization (BOLA)**, also called **IDOR** — **API1:2023** in the
OWASP API Security Top 10.

---

## 🏗️ Architecture

Three local services, no cloud dependencies:

```text
┌──────────────────┐        ┌──────────────────┐        ┌─────────────────────┐
│  frontend (Vite) │──────▶│ sentinel-engine   │──────▶│ vulnerable-demo-api  │
│  React dashboard │        │ FastAPI :8000    │        │ FastAPI :8001        │
│  :5173           │        │ scans + findings │        │ the scan target      │
└──────────────────┘        └──────────────────┘        └─────────────────────┘
```

| Service | Port | Purpose |
|---|---|---|
| `frontend/` | 5173 | Dark developer-tool dashboard: run scans, view evidence, verify fixes |
| `sentinel-engine/` | 8000 | Scanner API: OpenAPI discovery, deterministic BOLA checks, findings, generated pytest tests |
| `vulnerable-demo-api/` | 8001 | E-commerce demo API with **vulnerable** and **secure** modes (runtime switchable) |
| `generated-tests/` | — | Exported pytest regression tests (downloaded/copied from the UI) |

---

## 🎬 The Hero Demo

1. Start all three services (commands below).
2. Dashboard shows the demo API in **Vulnerable** mode.
3. Click **Run Authorization Scan**:
   - Scanner loads the target's OpenAPI contract.
   - Alice's own order returns `200 OK` ✔ (baseline)
   - Alice requests **Bob's** order → API returns **`200 OK` with Bob's private data** ✘
   - Scanner creates a **Critical** BOLA finding with request/response evidence.
   - Scanner generates a pytest regression test.
4. Click **Switch to Secure Mode** (the demo API now enforces ownership).
5. Click **Verify Fix**:
   - Alice requesting Bob's order now gets **`403 Forbidden`** ✔
   - The finding flips to **passed** — regression test green.

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

**Hero request**

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

- The scanner **only** accepts local targets: `localhost`, `127.0.0.1`, `::1`, `*.localhost`,
  and this project's Docker service hostnames. Arbitrary public URLs are rejected.
- **No stealth, brute force, bypasses, exploitation, or public scanning.** The only technique
  implemented is a deterministic own-resource vs. cross-resource comparison using synthetic data.
- `Authorization` headers are **redacted** (e.g. `Bearer alic...oken`) in every frontend-visible
  response.
- All data is synthetic. No production data, real credentials, or external services are used.
- AI explanations are optional, disabled by default, and have a deterministic fallback
  (Phase 6, not yet started).

---

## ▶️ Run Plan (local, no Docker)

Prerequisites: **Python 3.11+**, **Node 18+**, `pip`, `npm`.

**One-command demo launcher (recommended for the live demo):**

```bash
./run_all.sh                    # starts every existing service, waits for health, resets demo mode
./run_all.sh --keep-mode        # same, but leaves the demo API's current mode untouched
scripts/dev_daemon.sh start     # alternative: detached background services (logs in .run/)
scripts/dev_daemon.sh status    # or: stop
```

It starts the demo target API (:8001) today and will automatically pick up the scanner engine
(:8000) and frontend (:5173) as those phases land; logs go to `.run/*.log` and `Ctrl+C` stops
everything it started.

**Manual per-service startup:**

```bash
# 1) Target demo API — port 8001
cd vulnerable-demo-api
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --port 8001

# 2) Scanner engine — port 8000 (new terminal)
cd sentinel-engine
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --port 8000

# 3) Dashboard — port 5173 (new terminal)
cd frontend
npm install
npm run dev
```

Then open **http://localhost:5173**.

**Backend tests**

```bash
cd vulnerable-demo-api && venv/bin/python -m pytest -v
cd sentinel-engine && venv/bin/python -m pytest -v
```

Docker Compose (`docker compose up --build`) arrives in Phase 5.

---

## 📊 Status

Phased build with acceptance gates — see [TASKS.md](TASKS.md) for the live checklist.

| Phase | Scope | Status |
|---|---|---|
| 0 | Repo scaffold + plan | ✅ Done |
| 1 | Vulnerable demo API + tests | ✅ Done |
| 2 | Sentinel scanner engine | ✅ Done |
| 3 | Basic dashboard | ✅ Done |
| 4 | Presentation-ready finding details | ⬜ Next |
| 5 | Polish, Docker Compose, demo script | ⬜ Planned |
| 6 | Optional AI explanation (opt-in only) | ⬜ Blocked until approved |
