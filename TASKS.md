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

## Phase 1 — Target Demo API ✅ DONE

Planned: FastAPI app on :8001 with token auth, seed identities/orders, `vulnerable`/`secure`
modes (runtime-switchable via `POST /admin/mode`), `/health` exposing active mode, `/openapi.json`.

- [x] Endpoints: `/health`, `/api/products`, `/api/orders/{order_id}`, `/api/users/{user_id}`,
      `/api/users/{user_id}/orders`, `/api/admin/refunds`, `/admin/mode`, `/openapi.json`
- [x] Vulnerable mode: Alice gets HTTP 200 for Bob's order (acceptance test)
- [x] Secure mode: Alice gets HTTP 403 for Bob's order (acceptance test)
- [x] Alice can access her own order in both modes (acceptance test)
- [x] Admin can access Bob's order in secure mode (acceptance test)
- [x] 401 for missing/invalid token; 404 for nonexistent ids; mode persisted for process lifetime

**Verified (2026-09-19):**
- `pytest`: **26/26 passed** (`vulnerable-demo-api/venv/bin/python -m pytest tests -v`)
  - vulnerable mode: Alice→Bob order 200 w/ private fields; Alice reads Bob's full profile;
    Alice lists Bob's orders; customer triggers admin refund; 401 missing/invalid token; 404 unknown id
  - secure mode: Alice→Bob order 403; own order 200; admin→Bob order 200; cross-user profile
    and order list 403; customer refund 403; admin refund 200; 401 without token
  - `/openapi.json`: 200, OpenAPI 3.x, all 7 paths + `{order_id}`/`{user_id}` path params present
- Live uvicorn smoke test on 127.0.0.1:8001 (real HTTP): health mode badge, runtime mode switch,
  hero request 200 (vulnerable) → 403 (secure), admin access 200, `/openapi.json` 200.

**Assumptions / limitations:**
- `vulnerable` is the default mode on startup (matches the demo story).
- In secure mode, cross-user profile reads return **403** (spec: customers access only their own
  profile) rather than a redacted public-profile 200 — gives the scanner an unambiguous pass.
- Mode is in-process state (resets on restart); no persistence needed for the MVP.
- Corrupted UTF-16 README from the failed first turn was deleted and rewritten in UTF-8.

---

## Phase 2 — Scanner Engine ✅ DONE

Planned: FastAPI scanner on :8000 — fetches the target's OpenAPI contract, validates local-only
targets, runs deterministic BOLA checks (own-resource baseline → id mutation → cross-user probe),
captures evidence, applies severity rules, redacts tokens, generates pytest regression tests,
keeps scans in memory with GET /scan/{id} and findings endpoints.

- [x] `POST /scan`, `GET /scan/{scan_id}`, `GET /scan/{scan_id}/findings`, finding + test endpoints
- [x] OpenAPI fetched and parsed from the target; GET routes + path params discovered
- [x] Local-only target whitelist enforced (rejects non-local targets) (acceptance test)
- [x] BOLA detected Alice→Bob order in vulnerable mode (acceptance test)
- [x] Pass reported for same probe in secure mode (acceptance test)
- [x] Tokens redacted in scanner responses (acceptance test)
- [x] Regression test text generated per finding; `generated-tests/` export supported

**Verified (2026-09-19):**
- Engine pytest: **38/38 passed** (`sentinel-engine/venv/bin/python -m pytest tests -v`)
  - 16 target-guard unit tests (local accepted: localhost/127.x/10.x/192.168.x/[::1]/`demo-api`;
    rejected: public hosts, https, ftp, credentialed URLs, link-local)
  - 9 unit tests: redaction (`Bearer alic...oken`), spec-exact sensitive-field list, dotted-path
    detection (incl. nested + suffix keys), regression-test generation (valid Python, path-only
    request line, redacted header, `assert response.status_code in [401, 403]`)
  - 13 integration tests against a **real demo API subprocess**: vulnerable-mode finding for
    `GET /api/orders/{order_id}` (critical, Alice→Bob, own probe 200 baseline + cross 200,
    exposed `items/total/shipping_address`) and profile finding; secure-mode pass with observed 403
    and score 100; verify-fix before/after flow; no raw token anywhere in API output;
    non-local target → 422; unreachable local target → failed scan (no crash); scan 404s
- Live smoke (`scripts/live_smoke.py`, real demo subprocess + engine server on 127.0.0.1):
  **7/7 checks passed** — vulnerable: 3 findings (order, profile, **plus the cross-user order-list
  leak on `GET /api/users/{user_id}/orders`**), score 10; secure: 3 passes, score 100, order check
  observed 403; generated test compiles; non-local target 422
- `./run_all.sh` now auto-starts both services (demo-api :8001, scanner-engine :8000)
- Demo suite still green: **26/26**

**Assumptions / limitations:**
- Attacker = first identity with role `customer` (Alice); victim = next customer (Bob) — matches
  the spec's POST /scan example.
- MVP mutation mappings are fixed (`order-1001/1002`, `user-101/102`); endpoint→mapping matching
  is by path param name (`{order_id}` → order map, `{user_id}` → user map).
- Findings IDs are sequential per engine process (BOLA-001…); in-memory store (no SQLite) —
  scan history UI not in MVP scope.
- Severity: critical when the deterministic sensitive-field list hits the cross-user body
  (order + profile bodies here), medium if a protected resource returns 200 without sensitive
  fields; passes recorded as checks, not findings.
- Two probe models stored per finding/check: `own_resource` baseline + `cross_user` evidence.
- The generated test uses the redacted token (token values never leave the request path), so the
  copy-pasted test asserts with `Bearer alic...oken` — swap in the real token in your suite.

**Addendum — one-click Verify Fix API (2026-09-19):**
- New endpoint: `POST /scan/{scan_id}/verify` — re-probes every stored finding using a verify plan
  captured at scan time (base URL, attacker/victim identities, endpoint templates + ownership maps;
  tokens stay server-side). Original "was" evidence is snapshotted before any mutation; fresh
  "now" probes are attached. A finding flips to `pass` only on a fresh 401/403 cross-user probe.
- Response includes per-finding before/after (`was`/`now` status + observed code), fresh probe
  evidence, `demo_mode` read from the target's `/health`, `verified_count`, `all_verified`.
- Error contract: 404 unknown scan / scan without findings; 409 scan not completed or no verify
  plan; 502 target unreachable during verification (no 500s).
- New files: `app/scanner/verify.py`, `tests/test_verify.py`; `VerifyPlan` moved to
  `app/scanner/bola.py` (avoids an engine↔verify circular import); findings now carry a
  `verification` field. `conftest.py` `demo_server` yields the `Popen` handle and mode-restore
  teardown tolerates a killed server.
- Verified: engine pytest **43/43** (6 new verify tests: flip-to-pass with persisted finding
  update, still-fails case, 404 unknown scan, 404 no-findings scan, 502 dead-target, redacted
  fresh probes); live smoke **9/9** including "verify while still vulnerable does not flip" and
  "verify after fix: 200 fail → 403 pass, demo_mode=secure"; demo suite still **26/26**.

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
