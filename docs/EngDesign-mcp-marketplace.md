# Engineering Design: AgentGate MCP Marketplace

**Status:** Draft v1
**Author:** Albert
**Last updated:** 2026-05-02
**Related:** [PRD: MCP Marketplace](./PRD-mcp-marketplace.md)

---

## Context

AgentGate today is a hosted agent marketplace: a Python monorepo with five FastAPI services (gateway, registry, billing, orchestrator, web), Postgres + Redis on Railway, an SDK for Python agent developers, and a custom REST invocation protocol. We're pivoting the protocol surface to MCP while keeping most of the infrastructure underneath.

The core engineering bet: **most of the platform is reusable, but the protocol layer, the hosting model, and the credential model all need rebuilding.** This doc lays out what changes, what stays, and how we get there without breaking the surface that already exists.

---

## Goals

1. End-to-end MCP-native invocation: a host client (Claude Desktop, Cursor) connects to AgentGate, sees aggregated tools, calls them, and pays per the configured model.
2. Single-connection, multi-server aggregation: one MCP endpoint per user, fanning out to N backing servers.
3. Managed hosting for Python and Node.js MCP servers with reasonable cold-start performance and bounded per-tenant resource use.
4. Two-tier credential model: developer credentials (set at publish) and end-user credentials (set per subscription), both encrypted, both auditable.
5. Reuse of existing billing ledger, account model, and Stripe integration. Extensions, not rewrites.
6. Migration path from the existing agent runtime that doesn't break the small number of agents currently on the platform.

## Non-goals

- Implementing every MCP feature in V1. Resources and prompts can wait; we ship tools first, add resources second, sampling probably never (security model is too fraught for a multi-tenant host).
- Supporting languages beyond Python and Node.js initially. Go and Rust come later if there's demand.
- Building our own host client. We integrate with existing ones.
- Realtime streaming responses from tool calls. MCP supports this; we'll punt to V2.

---

## Architecture overview

```
                                   Claude Desktop / Cursor / Claude Code
                                                  │
                                                  │ MCP over stdio or SSE
                                                  ▼
                              ┌─────────────────────────────────────────┐
                              │          MCP Gateway (:8000)            │
                              │  - protocol bridge                       │
                              │  - per-user tool aggregation             │
                              │  - auth, rate limit, billing hold        │
                              │  - request routing                       │
                              └─────────────────┬───────────────────────┘
                                                │
              ┌─────────────────────────────────┼─────────────────────────────────┐
              │                                 │                                 │
              ▼                                 ▼                                 ▼
   ┌──────────────────┐             ┌────────────────────┐            ┌──────────────────┐
   │ Registry (:8001) │             │  Billing (:8002)   │            │ Hosting (:8003)  │
   │ - server catalog │             │  - ledger          │            │ - warm pool      │
   │ - tool index     │             │  - holds/settle    │            │ - per-server     │
   │ - search         │             │  - subscriptions   │            │   instances      │
   │ - ratings        │             │  - payouts         │            │ - lifecycle mgmt │
   └──────────────────┘             └────────────────────┘            └──────────────────┘
                                                                                  │
                                                                                  ▼
                                                                       ┌──────────────────┐
                                                                       │ Sandboxed MCP    │
                                                                       │ server processes │
                                                                       │ (per-user warm)  │
                                                                       └──────────────────┘

   ┌──────────────────────────────────────────────────────────────────────────────┐
   │ Web (:8004) — public marketplace, developer portal, end-user dashboard       │
   └──────────────────────────────────────────────────────────────────────────────┘
```

This preserves the five-service split from the existing AgentGate but reshapes responsibilities. Gateway becomes an MCP protocol terminator instead of a REST proxy. Orchestrator becomes Hosting. Registry, Billing, and Web are largely intact.

---

## Component design

### MCP Gateway

**Responsibilities:** terminate MCP connections from host clients, authenticate the user, aggregate tool listings from every server the user has subscribed to, route `tools/call` requests to the right backing instance, meter and bill, return results.

**Protocol surface.** MCP supports two transports: stdio (for local processes) and SSE (for HTTP-based servers). Local clients launch a small AgentGate stub binary that opens an SSE connection back to our gateway, so we standardize on SSE on the wire. The stub binary is a 5MB Go executable: it reads the user's API key from a config file, opens an SSE stream to `gateway.agentgate.com/mcp`, and bridges stdio to the SSE connection. Distribution: Homebrew, npm, scoop.

**Aggregation model.** When the gateway receives `tools/list` from a host, it returns the union of tools from every active subscription. Tool names are namespaced (`{server_slug}__{tool_name}`) to avoid collisions. The gateway maintains a per-user routing table cached in Redis keyed by `(user_id, namespaced_tool_name) -> server_id`.

**Tool call flow.**

1. Host calls `tools/call` with namespaced tool name.
2. Gateway authenticates user, looks up routing entry.
3. Gateway resolves billing rule for this server + tool. For per-call: place a hold on max(price). For subscription: verify subscription active, no hold needed. For BYO-credentials hosted: verify subscription, no per-call billing.
4. Gateway asks Hosting for a warm instance of the target server scoped to this user. If none, Hosting cold-starts one.
5. Gateway forwards the tool call to the instance, including injected credentials.
6. Gateway awaits response, settles the hold against actual cost (allows variable pricing later), records usage event.
7. Gateway returns response to host.

**Latency budget.** Target p50 of 50ms gateway overhead, p99 of 200ms. Cold-start of a backing server adds 1-3s and is unavoidable on first call; warm-pool hits should be sub-10ms routing.

**State.** Gateway is stateless except for in-process Redis-backed caches of routing tables and hold IDs. Crash-safe by design.

### Registry

**Responsibilities:** server catalog, tool indexing, search, ratings, install counts.

**Schema additions to existing `agents` table** (rename to `mcp_servers`):

```sql
ALTER TABLE agents RENAME TO mcp_servers;

ALTER TABLE mcp_servers
  ADD COLUMN runtime_kind TEXT NOT NULL DEFAULT 'python',  -- 'python' | 'node' | 'external_url'
  ADD COLUMN runtime_version TEXT,                          -- e.g. '3.12', '20'
  ADD COLUMN entry_point TEXT,                              -- 'server.py' or 'server.js'
  ADD COLUMN tool_schema JSONB,                             -- cached MCP tools/list response
  ADD COLUMN pricing_model TEXT NOT NULL,                   -- 'per_call' | 'subscription' | 'freemium' | 'byo_creds'
  ADD COLUMN pricing_config JSONB NOT NULL DEFAULT '{}',    -- per-tool prices, monthly fee, etc
  ADD COLUMN install_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN rating_avg NUMERIC(3,2),
  ADD COLUMN rating_count INTEGER NOT NULL DEFAULT 0;

CREATE TABLE mcp_tools (
  id UUID PRIMARY KEY,
  server_id UUID REFERENCES mcp_servers(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  input_schema JSONB,
  price_cents INTEGER,           -- override per-tool, nullable
  description_embedding JSONB,   -- vector once pgvector is available
  UNIQUE (server_id, name)
);

CREATE INDEX idx_mcp_servers_pricing ON mcp_servers(pricing_model);
CREATE INDEX idx_mcp_tools_server ON mcp_tools(server_id);
```

**Tool indexing.** When a developer publishes, we boot the server in a sandboxed builder, send `initialize` and `tools/list`, parse the response, and write rows to `mcp_tools`. We re-index on every version bump. The indexed tool descriptions go into the search corpus alongside the server-level description.

**Search.** Hybrid retrieval: BM25 over name + description + tool descriptions, plus semantic via embedding. Embedding currently broken in the codebase (placeholder OpenAI key) — this needs to be fixed regardless of pivot. pgvector unavailable on Railway Postgres; we either move Postgres to Supabase or run a small Qdrant instance for vector search.

### Hosting

**Responsibilities:** run developer-uploaded MCP servers in sandboxed processes, scale them per-user-per-server, manage warm pools, enforce resource limits, inject credentials at runtime.

**The per-user-per-server isolation question.** This is the hardest design call. Three options:

- **Single instance shared across all users.** Cheap but breaks the credential model — if a server holds end-user credentials, two users sharing one process is a data leak.
- **One instance per (user, server) pair.** Clean isolation but expensive and slow to cold-start.
- **One instance per server, with credentials injected per-call.** Compromise that requires servers to be stateless w.r.t. user identity. Most are; some aren't.

We go with **option 2 (per-user-per-server)** as the default, with an opt-in **option 3 (shared, stateless)** for servers that explicitly declare themselves stateless and don't accept end-user credentials. This is configurable in the manifest as `isolation: per_user | shared`.

**Runtime substrate.** Not Docker (Railway doesn't support DinD, and we want fast cold-starts). Instead:

- **Firecracker microVMs** via a small fleet of worker hosts on a cloud that supports nested virt (Hetzner bare metal, GCP, AWS bare-metal EC2). Cold-start ~125ms, isolation is real.
- Alternative: **gVisor + cgroups + seccomp** on shared Linux hosts. Faster cold-start but weaker isolation. Acceptable for trusted/audited servers, not for arbitrary uploads.

We start with gVisor for speed, plan a Firecracker migration once we have meaningful supply.

**Warm pool.** Per (user, server) pair, we keep an instance warm for 10 minutes after last use. If the user calls again within the window, no cold-start. After 10 minutes idle, instance is killed. Aggressive caching trades infra cost for UX latency. Tunable per server.

**Resource limits.** Default: 256MB memory, 0.5 vCPU, 30s wall-clock per tool call, no persistent disk. Egress allowed by default but logged. Limits raisable per-server with developer review (and potentially higher hosting fees).

**Credential injection.** Two channels:

1. **Developer credentials** are injected as environment variables at process start (`AGENT_CRED_OPENAI_KEY=...`). The server reads them via the SDK's existing `get_credential` helper.
2. **End-user credentials** are NOT injected as env vars. They're fetched at tool-call time via a sidecar API the server can call: `GET http://localhost:8123/end_user_cred/{name}` returns the user's stored credential. This means the credential is only present when the user is actually invoking, and never sits in env vars across invocations.

### Billing

**Responsibilities:** ledger, holds, subscriptions, payouts. Most of this exists; we extend.

**Existing primitives that survive:** prepaid USD credits in cents, double-entry ledger with `SELECT ... FOR UPDATE` for concurrent safety, billing holds, Stripe deposit Checkout sessions.

**New primitives needed:**

- **Subscription billing.** A new `subscriptions` table keyed by (user, server) with monthly anchor date. A nightly Celery job advances anchors, charges balances, and disables expired subs.
- **Per-tool pricing.** Pricing rules resolve in priority order: tool-specific price → server default price → free. Resolved at hold-placement time.
- **Stripe Connect for payouts.** Developers onboard to Connect Express, we transfer their share of revenue monthly minus take rate. We hold balances in our ledger and reconcile monthly.
- **Wholesale rates.** Some servers (Tavily, Exa) have a cost basis to a third party. We track this in `mcp_servers.pricing_config.cost_basis_cents` and the developer revenue share is computed off (price - cost_basis).

Take rate computation is a single function that the ledger consults at settlement: `compute_split(charge, server) -> (platform_cut, developer_credit, cost_basis)`.

### Credential vault

**Existing:** Fernet-encrypted credentials per agent in `agent_credentials` table.

**Extensions:**

```sql
ALTER TABLE agent_credentials RENAME TO mcp_credentials;

ALTER TABLE mcp_credentials
  ADD COLUMN scope TEXT NOT NULL DEFAULT 'developer',  -- 'developer' | 'end_user'
  ADD COLUMN user_id UUID REFERENCES accounts(id);     -- nullable; set only for end_user scope
```

**End-user credentials** are scoped to (user, server, name). They're set by the user via the dashboard or via an OAuth flow proxied through us. They're injected at tool-call time via the sidecar API described above, never written to disk in the runtime, and rotated on the user's request.

**OAuth flow proxy.** For services that require OAuth (Notion, Linear, GitHub), we run the OAuth dance on behalf of the user and store the resulting tokens in `mcp_credentials`. We refresh them as needed. The MCP server itself never sees the OAuth client secret — it only sees the resulting access token through the sidecar.

### Web (developer portal + end-user dashboard + public catalog)

**Existing:** Server-rendered FastAPI + Jinja2, dark theme, cookie auth.

**Extensions, not rewrites:**

- **Public catalog** — already exists, needs reskin and the addition of tool listings, ratings, and pricing model badges.
- **Developer portal** — extend the existing agent submission flow. Add: pricing model selector, per-tool pricing rules, runtime version pickers, credential schema declaration (which credentials does the server need vs. ask the end user for), Stripe Connect onboarding.
- **End-user dashboard** — extend the existing dashboard. Add: subscriptions list, per-server credential management, OAuth-per-service flows, usage analytics, install instructions panel with copy-paste config snippets per host client.

We do NOT rebuild this in React. The Jinja stack is fine for the surface area we have.

### Developer CLI

New surface, not in current codebase. Single binary distributed via pip and npm. Commands:

```
agentgate login             # opens browser to OAuth with the platform
agentgate init              # scaffolds a new MCP server project
agentgate dev               # runs server locally with the platform in dev mode
agentgate publish [path]    # uploads, indexes tools, creates listing
agentgate logs <slug>       # tails logs from hosted instances
agentgate version <slug>    # version a published server
agentgate revenue           # shows current month's earnings
```

The CLI is the primary developer surface. The web portal is for casual config; the CLI is for daily work.

---

## Data model summary

Tables surviving from current AgentGate, possibly renamed:

- `accounts`, `api_keys` — unchanged
- `categories` — unchanged
- `agents` → `mcp_servers` — extended (see above)
- `agent_credentials` → `mcp_credentials` — extended with scope and user_id
- `ledger_accounts`, `ledger_entries`, `billing_holds` — unchanged
- `invocations` — schema unchanged but populated from gateway tool calls instead of orchestrator agent runs
- `stripe_events` — unchanged

New tables:

- `mcp_tools` — per-tool metadata and pricing
- `subscriptions` — monthly subscription state
- `oauth_connections` — third-party OAuth tokens for end-user creds
- `host_connections` — track active SSE connections from host clients (for ops/debugging)

---

## Migration plan from current AgentGate

The current platform has a small number of agents and a handful of test accounts. Migration is straightforward:

1. **Phase 0 (week 0):** branch and tag the current codebase as `v0-agents`. Continue serving existing REST agent traffic from this branch indefinitely.
2. **Phase 1 (weeks 1-3):** build the MCP gateway in parallel as a new code path. New `mcp_servers` rows live alongside legacy agent rows. Existing billing infrastructure handles both.
3. **Phase 2 (weeks 4-6):** build hosting runtime (gVisor + warm pool), credential vault extensions, and the OAuth proxy. Land the first three seeded MCP servers internally.
4. **Phase 3 (weeks 7-8):** build developer CLI, extend web portal for MCP publishing, soft-launch with a closed beta of 10 developers.
5. **Phase 4 (weeks 9-12):** public launch with 10 seeded servers, marketing push to Claude Desktop and Cursor power users, observe.
6. **Phase 5 (months 4-6):** Firecracker migration if supply has grown, V2 features (subscriptions, OAuth-heavy integrations, streaming responses).

Existing REST agent endpoints stay live and supported but are deprecated for new signups. We give existing developers six months to either migrate (we provide a wrapper that exposes a REST agent as an MCP tool) or accept sunsetting.

---

## Phased rollout / what ships in V1

**V1 must-haves to go public:**

- MCP gateway with per-user aggregation
- Python runtime hosting with gVisor
- Per-call and subscription pricing models
- Developer credentials + end-user credential storage (no OAuth proxy yet — manual paste in dashboard)
- Marketplace catalog with semantic search working
- Developer CLI with `init`, `dev`, `publish`, `logs`
- 10 seeded MCP servers across the four pricing models
- Stripe Connect payouts

**V1 nice-to-haves that can slip:**

- Node.js runtime (Python first; Node second)
- OAuth proxy for end-user credentials
- Ratings and reviews
- Per-tool pricing within a server
- Freemium and BYO-credentials pricing models (start with per-call and subscription)

**V2 / explicitly later:**

- Firecracker microVMs
- Streaming tool responses
- MCP `resources` and `prompts` support
- Enterprise features (SSO, audit logs)
- White-label marketplace
- Realtime usage dashboards

---

## Operational concerns

**Observability.** Every tool call gets a trace ID that flows from gateway to backing server and back. OpenTelemetry to a hosted Honeycomb or similar. Per-server p50/p99 latency dashboards. Cost-per-invocation tracking by server.

**Abuse and fraud.** Per-user rate limits at the gateway. Anomaly detection on spend patterns. Manual review queue for any server requesting raised resource limits. Egress allowlists for high-risk servers (e.g. ones that fetch URLs).

**Cold-start performance.** Warm pool sized to predicted concurrent users per server. We start over-provisioned and right-size with data. Cold-start budget: 1.5s p50 for Python, 800ms p50 for Node.

**Hosting cost model.** Per-user-per-server isolation is expensive at scale. We need to model this carefully: at 10K active users × 5 servers each × 10min idle window, we have ~50K warm processes at peak. At 256MB each that's 12.5 TB of RAM. Untenable on Railway. The Firecracker plan assumes dedicated bare-metal hosts where we can pack 100+ microVMs per host.

This is the single biggest operational risk: **the unit economics depend on warm pool density.** Either we get density right (Firecracker, aggressive idle eviction, possibly per-server-not-per-user for safe servers) or the per-call business doesn't pencil.

**Security boundary.** Sandboxed servers must not be able to read other servers' filesystems, network to internal services beyond the credential sidecar, or escape the resource limits. gVisor + seccomp + a tight network policy gets us most of the way; a security review before any external developer can publish is mandatory.

---

## Open engineering questions

How do we handle MCP servers that need persistent state across invocations (a Postgres connection pool, a session token)? Two options: (1) require all state to be reconstructable from credentials, accept reconnect cost on cold-start; (2) provide a server-scoped persistent volume. Lean toward option 1 for V1 — it's strictly safer and most servers can tolerate it.

What do we do about MCP servers that need to make outbound calls back to the host (`sampling`)? V1 answer: not supported. The trust model is a mess (a malicious server could exfiltrate the user's conversation context via sampling requests). We watch the spec evolve and revisit.

How do we handle versioning when a developer pushes a breaking change to their tool schema? Proposed: every publish creates a new immutable version. Subscriptions pin to a version. Users must explicitly migrate to a new major version. Minor versions auto-update.

Where does Postgres live? Railway Postgres has been adequate but lacks pgvector. Options: move to Supabase, run a Qdrant sidecar for embeddings only, or wait for Railway to add pgvector. Probably option 2 in the short term.

Do we want to support running MCP servers the developer hosts themselves (an "external_url" runtime)? Pro: catches the long tail, low ops burden for us. Con: latency unpredictable, abuse harder to detect, billing precision worse. Probably ship it but hide it behind a "advanced" flag in the publish flow.

---

## Appendix: protocol surface we implement

V1 MCP methods supported by the gateway and required from hosted servers:

- `initialize` — required, server declares capabilities
- `tools/list` — required, gateway aggregates across user's servers
- `tools/call` — required, the meat
- `notifications/tools/list_changed` — required, triggers re-aggregation
- `ping` — required, liveness

Not in V1:

- `resources/*`, `prompts/*` — V2
- `sampling/*` — probably never
- `roots/*` — V2
- `logging/*` — V2

We commit to staying within 1 minor version of the official spec at all times.
