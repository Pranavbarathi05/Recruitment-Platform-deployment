# The assessment system

How assessments are planned, frozen, delivered and scored. The authoritative
implementation is the pure planner in
`dsc-recruit/apps/backend/services/assessment_planner.py` (fully documented in
its module docstring) and the orchestration in
`dsc-recruit/apps/backend/routers/assessment.py`.

## 1. Model in one picture

```
candidate semester
    → assessment_program      (scope / tier / max_domains / mcq_total / coding_enabled)
selected domains (1–2)         validated: active, allowed scope, exclusivity
    → assessment_module_config (OPTIONAL modules per domain + additional time)
    → plan_assessment()        deterministic, no DB access, no writes
    → AssessmentPlan           frozen (ids, counts, durations) → stored in
                               assessment_attempts.plan (JSONB, migration 017)
```

The plan is frozen for the life of the attempt: changing global config later
never affects a running (or completed) attempt. `PLAN_VERSION = 2`.

## 2. Scope, tier and semesters

`assessment_program` (migrations 014 + 018), one row per semester:

| `scope` | Semesters (per the seeded programme) | What that semester is offered |
|---|---|---|
| `organizational` | 1 | Organizational-Roles assessment only |
| `technical` | 3, 5 (tier `junior`/`senior` shapes the modules) | technical domains **and** Organizational Roles as a *standalone* assessment |
| `none` | 7 | nothing — `/assessment/available-domains` returns an empty list |

Key rules (all enforced in code, not convention):

- The **assessment mode follows the candidate's selection**, not the
  semester: selecting only the Organizational domain plans an *organizational*
  assessment even for a technical semester.
- **Organizational is mutually exclusive** with every other domain — a mixed
  selection is refused (`assert_organizational_exclusive`, error
  `invalid_domain_selection`). The organizational assessment is exactly one
  domain by definition.
- A technical selection is 1–`max_domains` (from the program row, ≤ 2) distinct
  technical domains.
- Domains carry `assessment_scope` (`technical` | `organizational`, migration
  015) — identity comes from this field, never from a name or hardcoded UUID.

## 3. Where each quantity comes from

| Section | Source | Rules |
|---|---|---|
| **Technical MCQ** | `assessment_program.mcq_total` (migration 018) | must be even (0–20 via the admin endpoint); **1 domain → all, 2 domains → half each**; drawn from that domain's active MCQs matching the candidate's **semester**; never truncated or topped up — an empty pool fails the plan (`insufficient_mcq_pool`). The final list is shuffled across domains when a seed is used |
| **Organizational MCQ** | `assessment_module_config.mcq_count` (required row, `applies_to = organizational`) | per its own module config |
| **Descriptive** | `assessment_module_config.descriptive_count` | **organizational scope only — technical assessments carry none**, regardless of any authored count |
| **Coding (DSA)** | `assessment_config.coding_problem_count` (global) + `assessment_program.coding_enabled` | **global and domain-independent**; organizational scope never carries coding; insufficient pool → `insufficient_coding_pool` |
| **Hands-On** | per-domain `assessment_module_config` (`hands_on_enabled`, `hands_on_count`, `hands_on_additional_minutes`, `hands_on_module`) | **senior technical only** — a guard prevents a junior row from ever delivering a challenge or its minutes; organizational has none |
| **Duration** | `assessment_config.duration_minutes` + sum of `hands_on_additional_minutes` of **enabled** hands-on modules | |

Module configuration rows are **optional for the technical scope** (missing row
= no optional module enabled) and **required for the organizational scope**
(its entire content derives from it, `missing_module_config` otherwise).

## 4. Question pools

| Pool | Table | Eligibility |
|---|---|---|
| MCQ | `mcq_questions` | `is_active` + `semester` matches + `domain_id` is the selected domain |
| Descriptive | `descriptive_questions` | `is_active` + domain in `domain_ids` (array — may span domains) |
| Hands-On | `hands_on_questions` | `is_active` + module/domain membership (below) |
| Coding | `coding_problems` | `is_active` (global) |

Selection is deterministic: candidates sorted by id, domains processed in
stable `(name, id)` order; with no seed the lowest-sorted eligible ids are
taken, with a seed `random.Random(seed)` draws (the seed is not part of the
config fingerprint). Descriptive and hands-on quotas are solved as an exact
**bipartite matching**, so a shared question satisfying one domain is
re-assigned when that is what it takes to place another — the plan is refused
only when *no* valid allocation exists.

## 5. Shared Hands-On modules

A hands-on challenge belongs to every domain that runs its module. Domains with
the **same** `hands_on_module` (e.g. App Development + Web Development both
running `sql_injection_employee_portal`) form **one requirement group**:

- the group's quota is the **largest** per-domain request — never the sum;
- one drawn challenge counts towards **every** member domain's requirement;
- genuinely different modules (`sql_wasm` vs `pandas_wasm`, …) stay in
  separate groups with independent quotas;
- the matcher still guarantees no challenge id is drawn twice across groups.

`hands_on_module` is authored on the module-config row (migration 024);
migration 025 auto-tags rows whose domain runs exactly one challenge type
(today: the SQL challenge) and deliberately leaves mixed/empty pools `NULL`,
which falls back to the pre-module per-domain allocation.

The frozen plan describes the offer as at most one practical module
(`module_kind=single`, `scoring=single`, one `hands_on` arm) — the
elective/max vocabulary exists so a future practical kind does not reshape
stored plans.

## 6. Delivered attempt

`assessment_attempts` holds the frozen plan in `plan` (JSONB) plus denormalised
totals (`total_questions`, `total_coding_problems`,
`total_descriptive_questions`, `total_hands_on_questions`,
`selected_*_ids`, `duration_minutes`, `started_at`, `expires_at`) and scores
(`score`, `max_score`, `mcq_score`, `coding_score`, …).

- **Start is idempotent**: an existing `in_progress` attempt is resumed exactly
  as stored (no re-selection), an expired one is scored first.
- **Statuses**: `in_progress` → `submitted` / `scored` / `reset`.
- **`termination_reason`** (migration 023): `NULL` = ordinary submission,
  `network_integrity_violation` = policy termination.
- Answers: `assessment_answers` (MCQ), `assessment_descriptive_answers`,
  `coding_submissions` + `coding_drafts`, `assessment_hands_on_results`
  (one row per attempt+question; 409 on a second submission).
- Admin remarks live in `assessment_attempts.admin_remark` (migration 011) and
  are **never** returned through candidate endpoints.

## 7. Scoring

- **MCQ**: correct option per question (correct answers are never sent to the
  candidate; scoring happens server-side at submit/expiry).
- **Coding**: sum of `coding_test_cases.points` for passed tests on the
  authoritative submit; Run is never scored.
- **Descriptive**: stored answers (word limits enforced at save); review is a
  separate admin-visible flow.
- **Hands-On**: full question `points` when verified, 0 otherwise — flag
  comparison (backend, trimmed exact) or the browser's binary WASM verdict.
  The browser never supplies the awarded points.
- Expiry: when `expires_at` passes the attempt is scored automatically on the
  next touch (start/current/attempt/questions/submit).

## 8. Proctoring policy in the plan

`assessment_config.network_integrity_monitoring` (migration 023, default
`false`, admin toggle) is read **once at start** and frozen into the plan as
`network_integrity_monitoring`. It changes no question, count or duration and
is deliberately excluded from `config_fingerprint`. The candidate workspace
reads the flag from the frozen plan, so flipping the global toggle can never
change a running attempt's behaviour.

## 9. Error vocabulary

`AssessmentPlanningError.kind` maps to HTTP 400 with `detail` like
`[insufficient_mcq_pool] ...`:

`no_assessment`, `invalid_program`, `invalid_domain_selection`,
`domain_not_found`, `domain_inactive`, `wrong_domain_scope`,
`duplicate_domains`, `missing_module_config`, `invalid_module_config`,
`insufficient_mcq_pool`, `insufficient_descriptive_pool`,
`insufficient_hands_on_pool`, `insufficient_coding_pool`.

`config_source` on new plans is always `modular`;
`legacy_technical_fallback` exists only as historical vocabulary for one
pre-modernisation frozen plan that must stay deserialisable.

## 10. Content inventory vs configuration

The planner's docstring is explicit that e.g. "40 MCQs per domain per
semester" is **question-bank inventory**, not a configuration value. Only
`mcq_total`, module rows, `coding_problem_count` and `duration_minutes`
configure an assessment. Nothing in the UI or API should present inventory
counts as knobs.
