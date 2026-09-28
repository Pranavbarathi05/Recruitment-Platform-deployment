# API reference

The endpoints that actually exist, read from the FastAPI routers in
`dsc-recruit/apps/backend/routers/` and the helper API in
`gateway/gateway-api/app/`. Nothing here is speculative — if an endpoint is not
in this document it is not mounted (for example `routers/questions.py` exists in
the tree but is **not** imported by `main.py`; the live catalogue endpoints are
in `routers/domains.py`).

## Conventions

- **Base URL**: through the Gateway the SPA calls everything same-origin under
  the `/_api` prefix, which Traefik strips: `POST /_api/auth/login` reaches the
  backend as `POST /auth/login`. In development the frontend calls
  `VITE_API_URL` (default `http://localhost:8000`) directly with no prefix.
- **Authentication**: cookie-only. `dsc_session` carries the Supabase JWT
  (hard-capped at 2 hours, no refresh flow). State-changing requests also send
  the CSRF cookie value back in the `X-CSRF-Token` header (double-submit).
  Admin endpoints require `profiles.is_admin` (403 otherwise).
- **Assessment capability**: mid-assessment endpoints additionally accept a
  second HttpOnly cookie, `dsc_assessment`, issued at attempt start and bound
  to `(profile_id, attempt_id, frozen expires_at)`. It keeps an in-flight
  attempt usable after the login session's 2-hour ceiling; it grants nothing
  else and is re-validated against the attempt row on every call.
- **Errors**: standard FastAPI `{"detail": ...}` with 401 (no/invalid session),
  403 (not owner / not admin), 404, 409 (already submitted), 400 (state
  violations such as expired attempt), 422 (validation).
- All example paths below are **backend paths** (after the `/_api` strip).

---

## Authentication — `routers/auth.py` (`/auth`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/auth/csrf` | none | Issue the CSRF cookie; returns `{"csrf_token": ...}` |
| POST | `/auth/signup` | none | Create a candidate account (Supabase Auth). Body: `email`, `password`, `fullName`, `usn`, `semester`, `branch`. Sets `dsc_session`; returns `{"user": {id, email}}` or `{"user": {..., "needs_confirmation": true}}` when email confirmation is pending |
| POST | `/auth/login` | none | Sign in. Body: `email`, `password`. Sets `dsc_session` + CSRF cookie |
| POST | `/auth/logout` | session | Revoke server-side, clear cookies → `{"status": "logged out"}` |
| GET | `/auth/me` | session | → `{"id", "email"}`; 401 without a valid cookie |
| GET | `/auth/assessment-access` | capability | → `{"attempt_id"}` when a live assessment capability exists, else 401. Used to resume an in-flight attempt after session expiry |

## Catalogue — `routers/domains.py`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/questions/domains` | none | All active domains: `[{id, slug, name, description, assessmentScope, questionCount, durationMinutes}]` (semester-agnostic catalogue — the candidate selection page does **not** use this; it uses `/assessment/available-domains`) |
| GET | `/questions/domains/{domain_id}` | none | One domain's detail |

## Assessment — `routers/assessment.py` (`/assessment`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/assessment/available-domains` | candidate | The **only** source for the selection page: resolves the candidate's semester → `assessment_program` → allowed scopes, returns `{semester, scope, tier, max_domains, domains: [...]}`; `domains: []` when the semester's scope is `none` |
| POST | `/assessment/start` | candidate | Plan + freeze one attempt. Body: `{"domain_ids": [1–2 ids]}`. Resumes an existing `in_progress` attempt instead of creating a second one. Returns `{attempt_id, total_mcq_questions, total_coding_problems, total_descriptive_questions, selected_descriptive_question_ids, total_hands_on_questions, selected_hands_on_question_ids, duration_minutes, domain_ids, expires_at}` and issues the `dsc_assessment` capability cookie. 400 with a machine-readable planning error (`insufficient_mcq_pool`, `wrong_domain_scope`, …) when no valid plan exists |
| GET | `/assessment/current` | candidate | Most recent in-progress attempt row (expired ones are scored first). `admin_remark` is stripped |
| GET | `/assessment/attempt/{attempt_id}` | candidate | One attempt (owner only); no scoring data; `admin_remark` stripped |
| GET | `/assessment/attempt/{attempt_id}/questions` | candidate or capability | MCQ section: questions **without** correct answers/explanations, plus saved answers; re-issues the capability cookie |
| PUT | `/assessment/attempt/{attempt_id}/answers` | candidate or capability | Save one MCQ answer per call: `{question_id, selected_option}` |
| PUT | `/assessment/attempt/{attempt_id}/descriptive-answers` | candidate or capability | Save a descriptive answer (`{question_id, answer_text}`); enforces the question's `word_limit` (400 when exceeded) |
| PUT | `/assessment/attempt/{attempt_id}/hands-on` | candidate or capability | Submit one Hands-On challenge (see below); **409 on any second submission** |
| POST | `/assessment/attempt/{attempt_id}/submit` | candidate or capability | Final submit: scores MCQ + coding + descriptive + hands-on, sets status, `termination_reason` for policy terminations (`network_integrity_violation`) or `null` for ordinary ones. Only one trigger wins (manual / timer / fullscreen / network guard) |

`PUT .../hands-on` body: `{question_id, submitted_flag?, submitted_input?, submitted_code?, validation_passed?, client_score?}`.
Flag challenges compare `submitted_flag` to the stored `expected_flag` (trimmed,
exact); WASM challenges trust only the browser's binary verdict
(`validation_passed`, `client_score` as legacy fallback) and let the **backend**
compute points from `hands_on_questions.points`. Response is always the neutral
`{"status": "submitted"}` — never correctness, score or the expected flag.

## Coding section — `routers/coding.py` (`/coding`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/coding/attempt/{attempt_id}/problems` | candidate | The attempt's coding problems with **public test cases only**, `starter_code` per language, `function_name`/`class_name`/`function_signature`, drafts and submission status. Hidden tests never leave the backend |
| PUT | `/coding/attempt/{attempt_id}/draft` | candidate | Autosave a draft (`{problem_id, source_code, language}`) |
| GET | `/coding/attempt/{attempt_id}/draft/{problem_id}` | candidate | Read one draft |
| POST | `/coding/attempt/{attempt_id}/run` | candidate | **Run** — public tests only, non-authoritative. Python 3 normally runs client-side (Pyodide) and never calls this; C/C++/Java do. Returns per-test results, `all_passed`, and on failure `input`/`expected_output`/`actual_output`; harness failures surface in `error`/`harness_error` |
| POST | `/coding/attempt/{attempt_id}/submit` | candidate | **Submit** — evaluates against **all** test cases server-side, computes `score`/`tests_passed`/`tests_total`, upserts `coding_submissions`, returns `{status, submission_id}` only (no score in the response) |

Languages: `python3`, `cpp`, `java`, `c` (`VALID_CODING_LANGUAGES` in
`schemas/coding.py`).

## Admin — `routers/admin.py` (`/admin`)

All require an admin session (403 for non-admins).

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/admin/domains` | List / create domains (`name`, `slug`, `description`, `duration_minutes`, `is_active`) |
| PUT | `/admin/domains/{domain_id}` | Update a domain |
| POST | `/admin/domains/{domain_id}/deactivate` \| `/activate` | Toggle a domain |
| GET/POST | `/admin/domains/{domain_id}/mcqs` | List / create MCQs (`semester` 1/3/5/7, `question_text`, `option_a..d`, `correct_option` A–D, `explanation`, `is_active`); GET accepts `?semester=` |
| PUT | `/admin/mcqs/{mcq_id}` | Update an MCQ |
| POST | `/admin/mcqs/{mcq_id}/activate` \| `/deactivate` | Toggle an MCQ |
| DELETE | `/admin/mcqs/{mcq_id}` | Delete an MCQ (restricted when referenced by attempts — see Admin Guide) |
| GET | `/admin/assessments/submissions` | Results list; query: `semester`, `branch`, `domain_id`, `search`, `sort` (`score`\|`percentage`\|`submitted_at`\|`name`), `order`, `limit`, `offset` |
| GET | `/admin/assessments/{attempt_id}/results` | Full result detail for one attempt (all sections, incl. hands-on verification/evidence for admins) |
| GET/PUT | `/admin/config` \| `/admin/config/{config_id}` | Assessment config rows. **Accepted fields only**: `name`, `coding_problem_count`, `duration_minutes`, `is_active`, `network_integrity_monitoring` (retired pre-modular knobs are stripped) |
| GET/PUT | `/admin/assessment-program/mcq-total` | Read / set the master technical `mcq_total` (0–20, even) on all active technical programmes |
| POST | `/admin/assessments/reset-all` | Reset every attempt |
| DELETE | `/admin/assessments/all` | Delete all attempts |
| POST | `/admin/assessments/{attempt_id}/reset` | Reset one attempt |
| DELETE | `/admin/assessments/{attempt_id}` | Delete one attempt |
| GET/PUT/DELETE | `/admin/assessments/{attempt_id}/remark` | Admin remark on a submission (10 000 chars max) |

## Admin content authoring

| Router | Prefix | Endpoints |
|---|---|---|
| `coding_admin.py` | `/admin/coding` | `GET/POST /problems`, `PUT /problems/{id}`, `POST /problems/{id}/activate` \| `/deactivate`, `DELETE /problems/{id}`, `GET/POST /problems/{id}/tests`, `POST /problems/{id}/tests/bulk` (JSON bulk upload), `PUT /tests/{id}`, `DELETE /tests/{id}` |
| `descriptive_admin.py` | `/admin/descriptive-questions` | `GET ""`, `GET /{id}`, `POST ""`, `PUT /{id}`, `DELETE /{id}`, `POST /upload-image` |
| `hands_on_admin.py` | `/admin/hands-on-questions` | `GET ""`, `GET /{id}`, `POST ""`, `PUT /{id}`, `DELETE /{id}` |
| `module_config_admin.py` | `/admin/assessment/modules` | `GET ""`, `GET /{domain_id}`, `PUT /{domain_id}` — per-domain module rows (`applies_to` junior/senior/organizational, `mcq_count`, `descriptive_count`, `hands_on_enabled`, `hands_on_count`, `hands_on_additional_minutes`, `hands_on_module`) |

Coding problem create/update fields: `title`, `slug`, `description`,
`difficulty` (`easy|medium|hard`), `constraints`, `input_format`,
`output_format`, `explanation`, `starter_code` (per-language dict),
`supported_languages` (subset of `python3/cpp/java/c`), `time_limit_ms`
(≤ 30000), `memory_limit_mb` (≤ 1024), `points` (1–100), `is_active`,
`function_name` (default `solve`), `class_name`, `function_signature`.

Hands-On create/update fields: `title`, `description`, `domain_ids`,
`challenge_type` (`sql_injection_employee_portal` | `sql_wasm` | `pandas_wasm`),
`difficulty`, `points` (default 10), `challenge_url`, `expected_flag`,
`is_active`; WASM-only: `schema_sql`, `dataset_json`, `starter_code`,
`validation_spec`, `expected_answer` (admin-only — never sent to candidates).

## Legacy — `routers/submission.py` (`/submission`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/submission/` | session | `evaluate_code()` legacy endpoint (still mounted, authenticated) |
| POST | `/submission/code` | session | V1 "receive but don't evaluate" endpoint |

## Gateway helper API — `gateway/gateway-api`

Reached at `/api/*` on the Gateway (priority 10, no prefix strip).

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness (Docker healthcheck) |
| GET | `/api/info` | `APP_ENV`, `APP_VERSION`, uptime |
| POST | `/api/session/start` \| `/heartbeat` \| `/end` | Candidate session bookkeeping (201 on start) |
| GET | `/api/session/{session_id}` | Read one session |
| GET | `/api/admin/sessions` | List sessions |
| GET | `/api/admin/health` | Gateway uptime + session counts |
| POST | `/api/execute` | Operator/smoke-test execution path (not used by the candidate UI). Body: `{language, source_code, test_cases: [{input, expected_output}], limits?, session_id?, attempt_id?, question_id?}` → `{status, language, execution_time_ms, tests[], total_tests, passed_tests, ...}`. Statuses: `accepted`, `wrong_answer`, `compilation_error` (HTTP 422), `runtime_error`, `time_limit_exceeded`, `invalid_language` (HTTP 422), `capacity_exceeded` (HTTP 503), `compiler_unavailable` (HTTP 502), `internal_error`. Languages: `python`, `c`, `cpp`, `java`, `sql` |
| GET | `/api/execute/health` | Active backend reachable? (`backend` field = `EXECUTION_BACKEND`) |
| GET | `/api/execute/languages` | Platform → backend language availability |

The full `POST /api/execute` contract example lives in
[`../gateway/DEPLOYMENT.md`](../gateway/DEPLOYMENT.md) → API contract.

## Health endpoints (no auth)

| Endpoint | Meaning |
|---|---|
| `GET /` (backend) | `{"status": "Healthy", "message": "API is working"}` |
| `GET /health` (challenge server) | `{"status": "ok"}` |
| `GET /` (Judge0) | 401 without token, 200 with `X-Judge0-Token` (use `/about` for a real check) |
