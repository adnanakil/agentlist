# CASA AL1 Readiness Pack — HAL (project rybo-410120)

Prepared 2026-07-09 for the ADA-CASA AL1 assessment Google requires by
**Oct 7, 2026** (email of 2026-07-09) to keep `gmail.readonly` (restricted
scope) verification moving. Companion to `GOOGLE_VERIFICATION.md`.

App under assessment: the HAL orchestrator (FastAPI, Python 3.12) deployed at
`https://www.tryhal.xyz` on Railway, plus shared packages `ag-common`/`ag-db`.
The iMessage bridge (separate Mac, stdlib-only script) never touches Google
user data directly — it relays chat text to/from the orchestrator over an
authenticated HTTPS API.

---

## 1. Scan status (pre-assessment, run 2026-07-09)

CASA accepts any scanner whose config covers the relevant CWEs with
PASS/FAIL results ([AST guide](https://appdefensealliance.dev/casa/tier-2/ast-guide));
labs typically run their own (TAC uses ESOF). Pre-scans run here:

| Tool | Config | Result |
|---|---|---|
| semgrep | `p/owasp-top-ten` + `p/python` | **0 findings** |
| bandit | full recursive over all three packages | 0 high, 1 medium, 12 low — all triaged below |
| pip-audit | workspace requirements export | 1 finding — **fixed** (mako 1.3.10 → 1.3.12, CVE-2026-44307; note `uv.lock` is gitignored and Docker builds resolve fresh via pip, so images pick up ≥1.3.12 on next build) |
| DAST-lite | header check on live domain | security headers were absent — **fixed** (`middleware/security_headers.py`: HSTS, nosniff, X-Frame-Options DENY, tight CSP, Referrer-Policy, Permissions-Policy) |

Regenerate any time:

```bash
uvx semgrep scan --config p/owasp-top-ten --config p/python \
  services/hal-orchestrator/hal_orchestrator packages/ag-common/ag_common packages/ag-db/ag_db
uvx bandit -r services/hal-orchestrator/hal_orchestrator packages/ag-common/ag_common packages/ag-db/ag_db
uv export --no-dev --format requirements-txt | uvx pip-audit -r /dev/stdin --no-deps
```

### Accepted bandit findings (justifications for the assessor)

- **B104 bind-all-interfaces (main.py, medium)** — uvicorn binds `0.0.0.0`
  inside the Railway container; TLS termination and ingress are Railway's edge.
  There is no direct route to the container port.
- **B404/B603 subprocess (services/skills.py)** — the skills shell runs
  operator-curated skill code in a subprocess with a denylist lint; since
  migration 029, model-authored *shared* skills cannot go live without admin
  approval (`hal_learning_candidates` quarantine, `growth_auto_publish=False`).
- **B110/B112 try/except/pass (7+1 sites)** — deliberate best-effort guards on
  non-critical paths (e.g. group-catalog enrichment must never break a user
  turn); each site logs or is intentionally silent by design comment.
- **B105 "hardcoded password"** — false positive: the string is Google's public
  token endpoint URL, not a credential.
- **B101 asserts (2)** — startup-time invariant checks (tool registry drift),
  not request-path authorization.

---

## 2. Data-flow description (the answer Google/assessors care most about)

**Google user data requested:** `gmail.readonly`, `calendar.readonly`,
`calendar.events`, `openid`, `email` — exactly what the code ships
(`services/google.py` SCOPES).

**Flow:** user texts HAL in iMessage → bridge POSTs the message to the
orchestrator (`Authorization: Bearer` bridge secret, fail-closed) → when the
turn needs Google data, the orchestrator calls Google APIs with the user's
OAuth token → the relevant snippets (event titles/times, email
subjects/snippets) enter that turn's context → the model provider
(Google Gemini API; Anthropic API as fallback) generates the reply → the reply
is texted back. Providers' API terms do not permit training on API data
(Limited Use compliant). **Caveat to keep true:** never route Google-connected
users' turns through providers without equivalent no-training terms (see
GOOGLE_VERIFICATION.md § Limited Use re GLM/Z.ai and OpenAI embeddings).

**Storage:** OAuth refresh/access tokens are Fernet (AES-128-CBC + HMAC)
encrypted at rest, keyed per user silo (`services/google.py`), key held only
in Railway env (`ENCRYPTION_KEY`). Email/calendar *content* is not stored in
dedicated tables; fragments may persist inside conversation history and
summaries in Postgres (Railway-managed; TODO(owner): confirm Railway's
at-rest encryption statement for managed Postgres for the SAQ). Message
content is **excluded from logs by default** (`log_message_content=False`).

**Deletion:** user can text "disconnect google" (revokes + deletes tokens) and
`/clear` (wipes conversation history); Stripe handles payments so no card data
ever touches HAL.

**Human access:** single operator; DB reachable only via Railway credentials;
bridge Mac is LAN-only with key-based SSH.

---

## 3. SAQ draft answers by ASVS theme

- **Authentication:** all non-public endpoints require a bearer secret
  (bridge) or `ADMIN_TOKEN` (admin routes); both fail closed and are validated
  at startup in production (`_validate_production_config`). Signed, expiring
  tokens for image-card URLs (`card_signing_key`, 15-min TTL).
- **Access control / tenant isolation:** all data is keyed by silo (phone
  number); group→DM data flow is one-way and membership-gated
  (`group_catalog`, `group_observations`); the model cannot trigger
  irreversible actions without server-side authorization derived from the
  user's actual inbound text (`services/action_policy.py`).
- **Input validation:** pydantic request models with hard bounds (12k-char
  text, 4 images, mime whitelist); request-size middleware (413 before body
  materialization); per-turn budgets (30 tool calls / 240 s); per-silo
  concurrency locks.
- **SSRF / outbound:** every model-directed fetch goes through
  `services/url_guard.py` — http(s)-only, no credentials in URLs, internal
  hostnames rejected, all resolved IPs must be public.
- **Injection:** SQLAlchemy ORM/bound parameters throughout (semgrep OWASP
  pass, 0 findings); no shell-string execution of user input.
- **Cryptography:** Fernet for tokens and stored credentials; HMAC-signed
  purpose-bound URLs; TLS everywhere in transit (Railway edge + HSTS).
- **Logging/monitoring:** structlog with content redaction by default;
  per-turn self-grades (`hal_turns`) reviewed via admin dashboard; unmatched
  Stripe payments alert the operator.
- **Availability/abuse:** durable outbox with lease/ack, idempotent inbound
  processing, worker leader election — a crash cannot double-send or
  double-charge.
- **SDLC:** monorepo with contract tests (`tests/test_hal_reliability_foundations.py`
  + 16 standalone suites), ruff/mypy, reviewed deploys from a clean committed
  tree.

**Gaps to close or answer honestly:**
1. No automated dependency-update process (answer: manual `pip-audit` cadence;
   consider a monthly cron).
2. No formal incident-response doc (a paragraph in the SAQ citing the admin
   alerts + single-operator model usually suffices at AL1).
3. TODO(owner) items in `routes/legal.py` (legal name, contact email) must be
   filled before the assessor reviews the privacy policy.
4. Confirm Railway managed-Postgres at-rest encryption for §2.

---

## 4. Engagement steps (owner)

1. Contact **TAC Security** via the link in Google's email (or
   tacsecurity.com → CASA) — request **AL1**, mention the Google-discounted
   rate (~$540/yr historically). Any ADA-authorized lab works; TAC is the
   discounted default. Expect: a scan (1–2 business days) + ~50-question SAQ.
2. Answer the SAQ from §2–3 of this doc.
3. Remediate anything their scan adds (this pack should make that near-empty),
   lab validates → submits the **Letter of Validation** to Google
   (~5–6 business days for Google to confirm).
4. **Reply to Google's verification email only once the assessment is
   underway/complete** — replying is what resumes their review.
5. Calendar note: this repeats **annually**; start ~2 months before the next
   due date.
