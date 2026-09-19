# API Sentinel — Phase Checklist

Hackathon phase gates. A phase is "done" only when its acceptance tests were actually run and their
results are recorded here.

---

## Phase 0 — Repository and Plan ✅ DONE

- [x] Inspect current directory (empty git repo; Python 3.14, Node 26, Docker 29 available)
- [x] Create structure: `frontend/`, `sentinel-engine/`, `vulnerable-demo-api/`, `generated-tests/`
- [x] Add `.gitignore` (Python, Node, env, local data, editors)
- [x] Add `requirements.txt` / `requirements-dev.txt` for both Python services
- [x] Write `README.md` (architecture, demo data, run plan, security/ethics constraints)
- [x] Create `TASKS.md` checklist (this file)
- [x] Define planned local startup commands (in README "Run plan")

**Verified:** structure exists on disk; no app code written yet (as instructed).
**Limitations:** none — nothing to break.

---

## Phase 1 — Target Demo API ⬜ NOT STARTED

Planned: FastAPI app on :8001 with token auth, seed identities/orders, `vulnerable`/`secure`
modes (runtime-switchable via `POST /admin/mode`), `/health` exposing active mode, `/openapi.json`.

- [ ] Endpoints: `/health`, `/api/products`, `/api/orders/{order_id}`, `/api/users/{user_id}`,
      `/api/users/{user_id}/orders`, `/api/admin/refunds`, `/admin/mode`, `/openapi.json`
- [ ] Vulnerable mode: Alice gets HTTP 200 for Bob's order (acceptance test)
- [ ] Secure mode: Alice gets HTTP 403 for Bob's order (acceptance test)
- [ ] Alice can access her own order in both modes (acceptance test)
- [ ] Admin can access Bob's order in secure mode (acceptance test)
- [ ] 401 for missing/invalid token; 404 for nonexistent ids; mode persisted for process lifetime

**Verified:** —
**Limitations:** —

---

## Phase 2 — Scanner Engine ⬜ NOT STARTED

Planned: FastAPI scanner on :8000 — fetches the target's OpenAPI contract, validates local-only
targets, runs deterministic BOLA checks (own-resource baseline → id mutation → cross-user probe),
captures evidence, applies severity rules, redacts tokens, generates pytest regression tests,
keeps scans in memory with GET /scan/{id} and findings endpoints.

- [ ] `POST /scan`, `GET /scan/{scan_id}`, `GET /scan/{scan_id}/findings`, finding + test endpoints
- [ ] OpenAPI fetched and parsed from the target; GET routes + path params discovered
- [ ] Local-only target whitelist enforced (rejects non-local targets) (acceptance test)
- [ ] BOLA detected Alice→Bob order in vulnerable mode (acceptance test)
- [ ] Pass reported for same probe in secure mode (acceptance test)
- [ ] Tokens redacted in scanner responses (acceptance test)
- [ ] Regression test text generated per finding; `generated-tests/` export supported

**Verified:** —
**Limitations:** —

---

## Phase 3 — Basic Frontend ⬜ NOT STARTED

Planned: React + Vite + TypeScript + Tailwind dark dashboard on :5173 — config panel (readonly
local targets, identity chips), mode switch, Run Authorization Scan, progressive scan steps,
summary cards (score, endpoints, severity counts, pass/fail), findings list.

- [ ] Switch demo API between vulnerable/secure from the UI (acceptance test)
- [ ] Trigger a scan and render summary + findings list (acceptance test)
- [ ] Graceful error handling for unreachable services (acceptance test)
- [ ] Severity badges (Critical/High/Medium/Pass) per palette

**Verified:** —
**Limitations:** —

---

## Phase 4 — Presentation-Ready Finding Details ⬜ NOT STARTED

Planned: finding detail panel with full evidence (redacted request incl. headers, response body,
expected vs observed, sensitive fields), impact/recommendation, copyable generated pytest block,
**Verify Fix** rerun, before/after verification state.

- [ ] Clicking a finding shows all evidence (acceptance test)
- [ ] Tokens redacted in UI (acceptance test)
- [ ] Generated pytest copyable (acceptance test)
- [ ] Vulnerable mode clearly shows 200 failure; Verify Fix shows 403 pass in secure mode (acceptance test)

**Verified:** —
**Limitations:** —

---

## Phase 5 — Polish, Testing, Docker ⬜ NOT STARTED

Planned: reliability/empty/error states, responsive styling, docker-compose for all three services,
demo script, final README instructions, fresh-setup verification.

- [ ] All backend tests pass (acceptance test)
- [ ] Frontend builds cleanly (`npm run build`) (acceptance test)
- [ ] `docker compose up --build` starts the whole stack (acceptance test)
- [ ] README documents exact startup + demo/presentation path

**Verified:** —
**Limitations:** —

---

## Phase 6 — Optional AI Explanation (blocked until explicitly approved after Phase 5) ⬜ BLOCKED

Planned (only on explicit approval): disabled-by-default "Explain for Developer" enhancement via
env-var config, deterministic template fallback, redacted synthetic metadata only, never required
for scanning or the demo.
