# Admin guide

What administrators can do, matching the live admin UI
(`dsc-recruit/apps/frontend/src/pages/Admin*.jsx`) and the admin routers. The
endpoint-level reference is [`API.md`](API.md); planning semantics are in
[`ASSESSMENT.md`](ASSESSMENT.md).

**Access**: admin pages require a login whose profile has `profiles.is_admin`
set — the backend returns 403 for everyone else.

## 1. Pages

| Route | Page | Purpose |
|---|---|---|
| `/admin` | `AdminPanel` | Domains, MCQs, assessment config, MCQ total, submissions/results, remarks |
| `/admin/coding` | `AdminCoding` | Coding (DSA) problems and test cases |
| `/admin/descriptive` | `AdminDescriptive` | Descriptive questions (organizational) |
| `/admin/hands-on` | `AdminHandsOn` | Hands-On challenges (flag + WASM) |
| `/admin/modules` | `AdminModules` | Per-domain module configuration |
| `/admin/assessments/:attemptId/results` | `AdminResults` | Full result detail for one attempt |

## 2. Domains (`/admin` → Domains)

- Create/edit: `name`, `slug`, `description`, `duration_minutes`, `is_active`.
- A domain's **assessment scope** (`technical` | `organizational`) is set in
  the database catalogue (migration 015/019/021); it decides which programme
  may offer it and the exclusivity rule. The Organizational domain must stay
  `organizational` — it can never be combined with other domains.
- **Activate / deactivate** keeps historical attempts intact; an inactive
  domain simply cannot be selected any more (`domain_inactive`).

## 3. MCQ questions (`/admin` → MCQs)

- Per domain **and semester** (1/3/5/7): `question_text`, four options,
  `correct_option` (A–D), `explanation`, `is_active`.
- Create, edit, activate/deactivate, delete.
- **Deletion is protected**: a question referenced by any existing attempt is
  rejected with 409 — deactivate it instead so historical results stay
  consistent.
- The **pool must cover the plan**: each selected domain+semester needs at
  least the number of MCQs the plan will draw (technical: `mcq_total` split
  across domains), otherwise starting an assessment fails with
  `insufficient_mcq_pool`.

## 4. Assessment configuration (`/admin` → Config)

Editable fields (retired pre-modular knobs are not accepted and not shown):

| Field | Meaning |
|---|---|
| `name` | config row label |
| `duration_minutes` | base duration for every attempt |
| `coding_problem_count` | the **global** number of DSA problems (domain-independent) |
| `is_active` | only the active row is used |
| `network_integrity_monitoring` | global toggle for the optional network-integrity monitor (default off). Frozen into each attempt's plan **at start** — flipping it never affects a running attempt |

**MCQ total** (separate control): `GET/PUT /admin/assessment-program/mcq-total`
sets the master technical `mcq_total` on all active technical programmes
(even numbers, 0–20). One domain gets all of it, two domains get half each.
Organizational programmes are untouched.

## 5. Module configuration (`/admin/modules`)

One row per **domain × family** (`junior`, `senior`, `organizational`):

| Field | Meaning |
|---|---|
| `mcq_count` | organizational MCQ quantity (ignored for technical — that comes from `mcq_total`) |
| `descriptive_count` | organizational only; technical assessments never carry descriptive questions |
| `hands_on_enabled` / `hands_on_count` | optional Hands-On module (senior technical only) |
| `hands_on_additional_minutes` | extra duration while enabled |
| `hands_on_module` | which challenge module the domain installs (e.g. `sql_injection_employee_portal`, `sql_wasm`, `pandas_wasm`) — drives cross-domain deduplication |
| `notes` | free-form |

Saving runs a **preflight** against the live pools: the form reports when the
configured counts exceed the eligible active questions (MCQ per semester,
descriptive/hands-on by domain overlap) so you do not author an assessment
that can never start. Missing rows are legal for technical families (no
optional module); the organizational family requires its row.

## 6. Coding problems (`/admin/coding`)

- Problem fields: title, slug, description, difficulty
  (`easy|medium|hard`), constraints, input/output format, explanation,
  per-language **starter code** (`python3`, `cpp`, `java`, `c`), supported
  languages, `time_limit_ms` (≤ 30000), `memory_limit_mb` (≤ 1024), `points`
  (1–100), and the **function model**: `function_name` (default `solve`),
  optional `class_name`, optional `function_signature`.
- Keep starter code consistent with the function model — the generated
  harness calls exactly `function_name` (optionally inside `class_name`), so
  a starter that defines a different function will fail every run.
- Test cases: created individually or via **bulk JSON upload** (a
  `{test_cases: [...]}` JSON body, up to 100 at a time); each carries
  `arguments` (JSON array of call arguments), `expected_output`, `is_public`
  (default **false** = hidden), `points` (1–10) and `ordering`.
  Candidate-facing code only ever receives the **public** ones — hidden tests
  are used exclusively by the server-side submit evaluation.
- Activate/deactivate/delete a problem (deletion is protected when attempts
  reference it).

## 7. Descriptive questions (`/admin/descriptive`)

- `question_text`, optional `image_url` (upload endpoint provided), optional
  `word_limit` (enforced when candidates save), `domain_ids` (a question may
  span several domains), `is_active`.
- Create/edit/delete — deletion protected against referenced attempts.
- Only the **organizational** assessment draws descriptive questions.

## 8. Hands-On challenges (`/admin/hands-on`)

Common: `title`, `description`, `domain_ids`, `difficulty`, `points`
(default 10), `is_active`, plus `challenge_type`:

| Type | Extra fields | Candidate experience |
|---|---|---|
| `sql_injection_employee_portal` | `expected_flag` (admin-only), `challenge_url` | iframe of the Employee Portal; flag verified server-side (trimmed exact) |
| `sql_wasm` | `schema_sql`, `dataset_json`, `starter_code`, `validation_spec`, `expected_answer` (admin-only) | browser-local SQL editor; validation spec run in the browser |
| `pandas_wasm` | same WASM fields | browser-local pandas editor |

The expected flag / expected answer **never leave the backend**. The browser
receives only what it needs to run the challenge (schema, dataset, starter,
validation spec).

## 9. Results, remarks and attempt lifecycle (`/admin` → Submissions)

- **List**: filter by semester/branch/domain, search by name/email/USN, sort
  by score / percentage / submitted_at / name; paginated.
- **Detail**: `/admin/assessments/:attemptId/results` shows every section,
  including Hands-On evidence, verification and scores, and coding results.
- **Remarks**: per-attempt admin remark (≤ 10 000 chars) via
  `GET/PUT/DELETE /admin/assessments/{id}/remark`. Remarks are admin-only —
  candidate endpoints strip `admin_remark` from every response.
- **Reset / delete** (destructive, confirm in the UI):
  - `POST /admin/assessments/{id}/reset` and `DELETE /admin/assessments/{id}` —
    one attempt;
  - `POST /admin/assessments/reset-all` and `DELETE /admin/assessments/all` —
    every attempt.
  Resetting returns a candidate to a startable state; deletion removes
  historical results — prefer **deactivate** for content, reserve deletion for
  test data.

## 10. Good authoring order

1. Domains active, correct scope.
2. MCQ pool per domain + semester (≥ the configured totals).
3. Descriptive pool (organizational) / coding problems + tests / hands-on
   challenges.
4. Module configuration (`/admin/modules`) with preflight green.
5. Config: duration, global coding count, MCQ total, network-integrity
   toggle.
6. Dry-run as a candidate (own account) before the drive.
