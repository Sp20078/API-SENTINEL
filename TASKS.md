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

## Phase 3 — Basic Frontend ✅ DONE

Planned: React + Vite + TypeScript + Tailwind dark dashboard on :5173 — config panel (readonly
local targets, identity chips), mode switch, Run Authorization Scan, progressive scan steps,
summary cards (score, endpoints, severity counts, pass/fail), findings list.

- [x] Switch demo API between vulnerable/secure from the UI (acceptance test)
- [x] Trigger a scan and render summary + findings list (acceptance test)
- [x] Graceful error handling for unreachable services (acceptance test)
- [x] Severity badges (Critical/High/Medium/Pass) per palette

**Verified (2026-09-19):**
- `npm run build` clean (strict `tsc -b` + Vite, 34 modules, no TS errors)
- **Browser-verified in the live preview against the real running stack** (Chrome, screenshots):
  - initial render: dark dashboard, header badges (Local Demo API dot + VULNERABLE mode),
    readonly local target/OpenAPI inputs, identity chips (Alice/Bob customers, Priya admin)
  - **Run Authorization Scan (vulnerable mode)**: 8-step progress panel completed, summary cards
    score **10**, 3 endpoints tested (5 discovered), **3 critical findings** with red badges,
    expected→observed 403→200 columns, finding IDs
  - **Switch to Secure**: header badge flipped to SECURE, notice shown, button states updated
  - **Scan in secure mode**: score **100**, 0 criticals, **3 passed checks** rendered as PASS rows,
    green "no authorization failures" notice
  - **Error handling**: demo API killed → header/target dots turned red within 5s, scan + mode
    buttons disabled (no crash); after restart the UI recovered
- Fixed during verification: Vite bound to IPv6-only (`host: true` now binds v4+v6 so
  127.0.0.1:5173 works), duplicated "GET GET" method prefix in finding rows, engine test-suite
  cross-talk with a running demo (conftest now skips demo-dependent tests when :8001 is busy)
- Backend suites re-verified after all changes: engine **43/43**, demo **26/26**
- New helper: `scripts/dev_daemon.sh start|status|stop` (setsid-detached services + logs in
  `.run/`); `./run_all.sh` unchanged and still works

**Assumptions / limitations:**
- Finding-detail panel, token-redaction display proof, and Verify Fix button land in Phase 4
  (API client already exposes the endpoints).
- Progress steps animate client-side while the engine runs the real scan synchronously —
  the spec's "realistic steps, preferably streamed or visually progressive".
- Demo identity tokens are hardcoded constants in the client (synthetic demo data; the engine
  redacts them in every response).

---

## Phase 3L — Live Real-World Provider Data ✅ DONE

Planned: the Trust Router demo runs on real data by default. Provider simulators resolve every
request through a live → cached → synthetic chain (free, keyless upstreams), stamp provenance,
and the engine + dashboard carry that provenance through evidence, audit, and UI.

- [x] `live_weather.py` — Open-Meteo geocode + current conditions (keyless, ≤1.8 s budget,
      10-min cache TTL, 30-min stale-serving window, circuit breaker, env kill switch)
- [x] `live_fx.py` — Frankfurter/ECB rates with inverse-rate computation and `rate_date`
- [x] `/data-mode` endpoints + per-request `?data_mode=` override (default: live)
- [x] Engine carries `data_source` (live/cached/synthetic) through attempts, canonical response,
      and the `primary_call`/`backup_call` timeline details; degraded responses carry none
- [x] Dashboard provenance badges (🌐 LIVE · 🕒 CACHED · 🧪 SYNTHETIC) replace the old
      "synthetic-only" labels; final-response card shows real values with honest provenance
- [x] Tests: provider suite runs fully offline by default (`conftest.py` sets
      `TRUST_ROUTER_LIVE_DATA=0`); live tests mock the HTTP seam — no real network in CI

**Verified (2026-09-20):**
- weather-providers pytest: **28/28 passed** (`weather-providers/venv/bin/python -m pytest -v`); engine full suite: **63 passed / 9 skipped** (skips are demo-subprocess tests that defer to a running :8001)
- engine Trust Router suites: **29/29 passed** (incl. 3 new provenance-passthrough tests)
- Live end-to-end smoke over real HTTP: `/primary/weather?city=Berlin` → real Open-Meteo reading
  (16.5 °C, light rain, `data_source: cached` — a recent live fetch served within its TTL);
  `/primary/fx?base=USD&quote=INR` → live ECB rate 95.88 with `rate_date`; Trust Router
  `/trust-router/request` carried `response.data_source` for both categories; `stale_data` fault
  mode over live data still fell back to the backup (trust 99); `?data_mode=synthetic` answered
  offline with `data_source: synthetic`
- Frontend `npm run build` clean (37 modules)

**Addendum — frontend bug-review fixes (2026-09-20):**
- New engine endpoint `GET /trust-router/primary-mode?category=…` (mirrors the simulator's real
  state; 422 unknown category, 502 simulator unreachable) + test.
- Trust Router tab now re-syncs its mode display from that endpoint on mount and on every
  category switch — fault modes are per-category on the backend, and the UI previously kept one
  shared mode value (wrong select value / stale "primary mode:" chip after switching).
- App.tsx header chip and footer no longer claim "synthetic only" — they reflect live-by-default
  data with offline fallback; AttemptCard no longer renders an empty wrapper when a provider
  attempt carries no provenance marker.

**Assumptions / limitations:**
- The engine's freshness policy (≤30 min) judges live data honestly: ECB FX rates publish once
  per working day, so `observed_at` is the *retrieval* instant and the ECB publication date
  travels separately as `rate_date`.
- Only `live_weather.py`/`live_fx.py` may leave localhost; the engine and scanner stay
  loopback-only. `TRUST_ROUTER_LIVE_DATA=0` forces the fully-offline synthetic tier (CI default).
- Provenance is the only raw provider *value* the engine stores — a deliberate, bounded
  exception to the "field names only" audit rule.

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
