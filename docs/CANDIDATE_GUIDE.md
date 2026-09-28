# Candidate guide

What a candidate experiences, matching the live UI
(`dsc-recruit/apps/frontend/src/pages/`). No internal implementation details —
operators and developers should read [`ASSESSMENT.md`](ASSESSMENT.md) and
[`ARCHITECTURE.md`](ARCHITECTURE.md) instead.

## 1. Signing in

- Open `http://<GATEWAY_LAN_IP>/` — nothing to install, any modern browser.
- **Sign up** at `/signup`: full name, email, USN, semester, branch, password.
  If email confirmation is required you will be asked to confirm first.
- **Sign in** at `/login` with email + password. Sign-in sessions are
  hard-capped at **2 hours**; a *running assessment* keeps working even if
  the login session itself expires (you will not be bounced to the login
  screen mid-attempt — and if you are ever asked to log in again, your
  attempt resumes exactly where it was).

## 2. Instructions (`/instructions`)

Read the instructions page first — it describes the sections your assessment
may contain (MCQ, Descriptive, Hands-On, Coding — your workspace shows only
the sections your selection produced, each tab labelled with its live count)
and the compliance rules:

- complete the assessment independently; follow the invigilator's and the
  platform's instructions;
- use only permitted resources; keep the environment unchanged;
- remain in the assessment environment for the whole duration;
- do not bypass platform controls, do not share questions/answers/code/flags;
- submit work only through the platform.

**Warnings that matter:**

- check everything before the final submit;
- **Hands-On submissions are one-shot server-side** — a second submission is
  rejected; **coding problems lock in the interface** after you press Submit
  (the editor, Run and Submit are disabled);
- watch the timer;
- leaving fullscreen or tripping other integrity controls can terminate the
  assessment.

**Need help?** Contact the nearest DSC invigilator immediately — that is the
official channel for technical problems.

## 3. Choosing domains (`/domains`)

- The list shows only the domains **your semester** is offered — you cannot
  pick a wrong one.
- Select up to your programme's limit (typically 1 or 2 domains).
- **The Organizational domain is exclusive**: it cannot be combined with any
  other domain. Select it alone, or choose technical domains only (the page
  shows this notice live).
- Press **Start Assessment**. Fullscreen is requested as part of that click;
  the attempt is created once and resumes if you come back (refresh, re-login)
  while it is running.

## 4. The workspace (`/assessment/<attemptId>`)

A viewport-locked page with:

- a **header** with the countdown timer (warning state at the last 5 minutes),
  fullscreen status, and the tab bar: `MCQ (n)`, `Descriptive (n)`,
  `Hands-On (n)`, `Coding (n)` — only the sections your assessment contains;
- a **Finish / Submit** button — the authoritative end of the attempt.

The timer is frozen from your start time: it keeps running while you switch
tabs or questions. When it reaches 0 the attempt is submitted automatically
with whatever you had saved.

### MCQ

Click an option to answer; answers autosave as you go. You can revisit
questions freely. Answers are scored only at the end.

### Descriptive (organizational assessments)

Type your answer; the question's word limit is enforced while saving. Answers
autosave.

### Coding

- Pick the language from the problem's supported list (Python 3, C++, Java, C).
- **Run** — feedback only, uses the public test cases shown in the statement:
  - *Python 3 runs entirely in your browser* (no code leaves your machine; an
    infinite loop cannot freeze the page — the run is terminated on timeout);
  - C/C++/Java runs on the server.
    Run results are **never** scored.
- **Submit** — authoritative: your code is evaluated server-side against
  *all* test cases (public + hidden). The response only confirms the
  submission — per-test results and your score are not shown.
- Your code autosaves as a draft per problem — switching questions or
  reloading restores it.

### Hands-On

Your assessment shows only the challenges it contains:

- **SQL Injection challenge** — an embedded "Employee Portal" (same-origin
  iframe at `/challenge/`). Exploit the login form and submit the flag.
  **One submission per challenge.** You are not told whether the flag was
  correct.
- **SQL (WASM)** — a browser-local SQL editor over the challenge dataset;
  Run validates your query, Submit sends the verdict. One submission.
- **Pandas (WASM)** — a browser-local Python/pandas notebook-style editor;
  same Run/Submit semantics. One submission.

## 5. Fullscreen and integrity rules

- The assessment must stay in **fullscreen**. If you leave it, a blocking
  overlay appears with a **15-second countdown** and a "Return to fullscreen"
  button:
  - return within the countdown and nothing happens (the timer keeps running);
  - let it reach zero and the attempt is **submitted automatically** through
    the same path as the Finish button.
- If fullscreen could not be inherited (deep link or refresh), you will be
  asked to click "Enter fullscreen" — the assessment does not start without it.
- If your programme has **network-integrity monitoring** enabled by the
  administration, the workspace periodically checks that your machine's
  network is intact while the attempt is active. A *confirmed* reachability
  violation finalises the attempt with a network-integrity termination
  reason. Helper failures (tool not installed, slow, no reply) never
  terminate an assessment.
- There is exactly one final submission per attempt: manual finish, timer
  expiry, fullscreen timeout and network termination all share the same
  single-submission guard — whichever fires first wins.

## 6. After submitting

- You land on the confirmation page (`/assessment/<attemptId>/submitted`).
- Scores are final; admin-visible remarks may be added by reviewers but are
  not part of the candidate UI.
- Historical attempts cannot be re-opened or edited.

## 7. Troubleshooting (candidate-side)

| Symptom | What to do |
|---|---|
| Page will not load | Check you are on the Gateway address and the network; tell the invigilator |
| "Failed to fetch" on login | The platform is restarting — wait a moment and retry; then tell the invigilator |
| Fullscreen will not engage | Allow the request when prompted, close other pop-up blockers, click "Enter fullscreen" in the workspace |
| Editor looks blank / Run never finishes | Wait for first-time runtime initialisation (a few seconds), then Run again; if it persists, tell the invigilator |
| Screen frozen after leaving fullscreen | The overlay is blocking by design — click "Return to fullscreen" |
| Any other issue | **Contact the nearest DSC invigilator immediately** |
