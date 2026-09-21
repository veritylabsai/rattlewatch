# Security Policy

This document states Rattlewatch's security posture, the controls that are
implemented and tested, and â€” importantly â€” what is **not** protected. Claims
here are backed by tests in `tests/test_api.py`; if a claim has no test, treat it
as unverified.

---

## 1. Scope

Rattlewatch is a **public, read-only** API and MCP server serving **public-domain
government data** (CPSC recall records) and curated citations to public
regulation. It has:

- no user accounts
- no login, sessions, or cookies
- no payment card data
- no personal data of any kind stored or processed
- no write endpoints

The attack surface is therefore narrow: availability, resource consumption, and
data integrity of the published corpus.

## 2. Assets

| Asset | Sensitivity | Notes |
|---|---|---|
| Recall corpus (SQLite in the image) | Public | Derived from the CPSC public API |
| Curated facts + citations | Public | Each cites an official source URL |
| API keys (premium tier) | **Secret** | Env vars on the Cloud Run service |
| Service account credentials | **Secret** | Managed by Google Cloud, never in this repo |
| GCP project `verity-labs` | Sensitive | Billing/quotas, not data confidentiality |

## 3. Threat model

| Threat | Realistic? | Mitigation |
|---|---|---|
| Resource exhaustion / CPU burn via repeated queries | **Yes â€” this was a real bug** | Corpus caching (560Ã— faster); query length bounds; rate limiting |
| Excessive request volume / cost amplification | Yes | Cloud Run `max-instances=3` cap; per-instance rate limit |
| Injection (SQL, etc.) | Low | All SQL uses parameterised statements; covered by a test |
| Information disclosure via errors | Yes | Global exception handler returns a generic message; no stack traces |
| Secret exfiltration via the repo | Moderate | No secrets in the repo; `.gitignore` blocks `.env`, `*.pem`, credentials JSON |
| Container escape / privilege escalation | Low | Container runs as unprivileged UID 10001, no shell, no added capabilities |
| Supply-chain compromise of a dependency | Moderate | Minimal dependency set (4 runtime deps) â€” see Â§7 |
| Abuse of the premium tier | N/A today | Fails closed: 402/503, never grants access without a valid key |

## 4. Implemented controls

All of the following are enforced and tested.

**Input handling**
- Query strings bounded at **256 characters** â€” enforced at *both* the FastAPI
  layer and independently inside the engine (defence in depth).
- `limit` bounded to 1â€“50; `subject` â‰¤ 64 chars; `since` â‰¤ 40 chars.
- Request bodies over 4 KB rejected with `413` before reaching a handler.
- All SQL is parameterised; a `'; DROP TABLE --` payload is asserted inert.

**Resource protection**
- The matching corpus (recalls + token sets + IDF) is **cached per process** and
  invalidated by a cheap data fingerprint. This replaced a per-request rebuild of
  the entire corpus â€” measured at **215 ms â†’ 0.4 ms (560Ã—)** for 3,000 records.
- Per-client sliding-window rate limit (default 60 req/60 s, env-tunable).
- Cloud Run `max-instances=3` bounds blast radius and cost.

**Authentication (premium tier only)**
- Requires an API key compared using `hmac.compare_digest` (constant time).
- **Fails closed.** With no key configured the tier returns `503`; with a wrong
  key it does not authorise. There is no path where a misconfiguration grants access.
- The x402 endpoint is a **stub and verifies no payment**. It returns `402` and
  never returns data. It must not be described as a working paywall.

**Transport & response**
- TLS terminated by Cloud Run (HTTPS only).
- Security headers on every response: `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Cross-Origin-Resource-Policy: same-origin`, `Cache-Control: no-store`.
- CORS **denied by default**; origins must be explicitly allow-listed via
  `RATTLEWATCH_CORS_ORIGINS`.
- Error responses contain no stack traces, file paths, or internal identifiers.

**Container**
- Runs as unprivileged user **UID 10001**, no login shell, exec-form `CMD`
  (PID 1, signals delivered directly).
- `PYTHONDONTWRITEBYTECODE` set; no build toolchain in the runtime image.

**Cloud**
- Public access is limited to the two Cloud Run services; no public buckets.
- The refresher service account holds only the roles its job needs.
- No service-account keys were created â€” no long-lived credentials exist.

## 5. NOT protected â€” known limitations

Stated plainly so nobody assumes a guarantee that does not exist.

1. **The public tier is unauthenticated by design.** Anyone may call it. It is a
   public read-only dataset; the goal is availability, not access control. There
   is no per-user identity, so abusive users cannot be individually blocked.
2. **Rate limiting is per-instance and in-memory.** Cloud Run may run up to 3
   instances, so the effective global limit is up to 3Ã— the configured value, and
   counters reset when an instance is recycled. It is a coarse guard against
   accidental runaway loops, **not** a defence against a determined attacker.
   A global limiter would require a shared store (e.g. Redis/Firestore) â€” not built.
3. **No WAF, bot mitigation, or DDoS protection** beyond Cloud Run's platform
   defaults and the instance cap. A volumetric attack would still cost money.
4. **API keys are stored as plain environment variables**, not in Secret Manager.
   Migrating to Secret Manager is recommended before real revenue depends on them.
5. **Dependencies are pinned by minimum version, not by hash.** No lockfile and no
   SBOM is produced in CI. `pip install -r requirements.txt` will pick up newer
   releases on rebuild.
6. **Data freshness is daily, not continuous.** A Cloud Run Job rebuilds the
   image (re-ingesting the live CPSC feed) and redeploys both services, triggered
   by Cloud Scheduler at **06:00 UTC daily**. The corpus can therefore be up to
   ~24 hours stale. Freshness is **publicly visible** via `/stats`
   (`corpus_built_at`, `data_age_hours`) â€” deliberately, because a stale
   "current ground truth" service should be detectable by anyone relying on it.
   A scheduled check (`.github/workflows/health.yml`, 09:00 UTC) fails if the
   corpus exceeds 36 hours, so a silent refresh failure surfaces as a failed
   workflow run rather than going unnoticed.
7. **`/docs` (OpenAPI) is public.** Intentional for an agent-facing API.
8. **No security review has been performed by a third party.** These are the
   author's own controls and tests.

## 6. Data handling

- No personal data is collected, stored, or logged. There are no cookies and no
  tracking.
- Recall data originates from the public CPSC REST API and is attributed with a
  source URL on every record.
- Client IPs are used transiently for rate limiting and are **not persisted** â€”
  counters live in process memory only.

## 7. Dependencies

Runtime dependencies are deliberately minimal: `mcp`, `fastapi`,
`uvicorn[standard]`, `httpx`, `PyYAML` (plus `pydantic` transitively). Every
dependency is a supply-chain risk; each addition should be justified.

## 8. Reporting a vulnerability

Until a dedicated address exists, open a **private security advisory** on the
GitHub repository rather than a public issue. Please include reproduction steps
and impact. No bug bounty is offered.

## 9. Verified vs unverified

| Claim | Status |
|---|---|
| Input bounds, SQL-injection inertness, security headers, no stack-trace leakage | **Tested** (`tests/test_api.py`) |
| Premium tier fails closed; wrong key does not authorise | **Tested** |
| Rate limiting returns 429 under load | **Tested** |
| Corpus caching removes the per-request rebuild | **Tested + benchmarked** |
| Container runs as non-root | **Configured**, not asserted by an automated test |
| Cloud Run IAM least-privilege | Manually reviewed, not automatically verified |
| Absence of vulnerabilities generally | **Not established.** No third-party review or pentest |
