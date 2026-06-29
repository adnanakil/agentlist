# PRD: AgentGate MCP Marketplace

**Status:** Draft v1
**Author:** Albert
**Last updated:** 2026-05-02

---

## TL;DR

AgentGate pivots from a horizontal agent marketplace to **the monetization, hosting, and discovery layer for the MCP ecosystem**. We become the Stripe + Heroku + Algolia of MCP: developers publish MCP servers to us, we host them, meter them, bill end users, and pay developers out. End users connect their Claude Desktop, Cursor, or Claude Code to a single AgentGate endpoint and instantly gain access to every monetized server in the registry — no per-server OAuth dance, no local hosting, one bill.

We're not building an agent platform. We're building the commercial substrate underneath the protocol Anthropic explicitly chose not to host.

---

## Problem

MCP adoption has exploded since the protocol launched, but the commercial layer is missing.

**For developers building MCP servers:** there is no path to monetization. They publish on GitHub, get stars, and get nothing. Hosting is a hassle (every server needs to be a long-lived process, often with credentials, often consuming paid third-party APIs). Authentication is half-baked — most servers ship with a "set this env var" README and call it done. There is no rate limiting, no abuse prevention, no metering, and no payout pipeline.

**For end users consuming MCP servers:** discovery is broken. The official MCP registry is sparse and unranked. Users find servers via Twitter screenshots and word of mouth. Installation is per-server, often involves cloning a repo and editing a JSON config, and breaks on updates. Authenticating to the underlying service (Linear, Postgres, Stripe, Notion) requires a separate OAuth flow per server, run from the user's own machine.

**For paid third-party APIs (Google Maps, Tavily, Exa, BrightData, etc.):** they want to be MCP-accessible because that's where attention is, but they don't want to operate consumer-grade billing for individual users buying $5/month of capacity. They want a wholesale buyer.

The platform owners (Anthropic, OpenAI, Cursor) have all signaled they want this layer to exist but don't want to build it. Anthropic in particular published the protocol and walked away from hosting. That leaves a deliberate vacuum for a third party.

---

## Goals

1. Become the default place developers publish monetized MCP servers, measured by share of new MCP servers launched with a payment model.
2. Become the default place end users discover and connect to MCP servers, measured by active installs across host clients (Claude Desktop, Cursor, Claude Code, Windsurf).
3. Make it dramatically faster to launch a paid MCP server than to roll your own — target: 10 minutes from "I have a Python file" to "I have a published, billable MCP server with a public listing."
4. Build commercial primitives flexible enough to support the four pricing models that have emerged in the wild: per-call metering, subscription, freemium-with-paid-tools, and BYO-credentials hosting.

## Non-goals

- We are not building agents. The intelligence lives in the host model (Claude, GPT, Cursor). We provide capability surface, not reasoning.
- We are not building our own host client. Claude Desktop and Cursor are the clients; we plug into them.
- We are not building a free MCP directory. Free servers are welcome but the business is paid servers and paid users.
- We are not entering the MCP protocol design conversation. We implement the spec; we don't fork it.
- We are not building enterprise SSO, SCIM, audit logs, or VPC peering in V1. That's a V2 conversation once we have a paying enterprise pipeline.

---

## Target users

**MCP server developer (primary supply side).**
A solo developer or small team that has either (a) wrapped a paid API they pay for and want to resell, (b) built a useful tool they want to charge for, or (c) maintains an open-source MCP server and wants donations or paid tiers. They are technically proficient, comfortable with Python or Node, and frustrated that publishing on GitHub gets them nothing.

**MCP server consumer (primary demand side).**
A power user of Claude Desktop, Cursor, or Claude Code. They use AI in their daily workflow, are willing to pay for tools that save them time, and are actively looking for capabilities to plug into their assistant. They are NOT enterprise IT buyers in V1 — those come later.

**Wholesale API providers (secondary supply side).**
Companies like Tavily, Exa, BrightData, SerpAPI, Apify who want their API surface available in MCP form without operating end-user billing. They negotiate wholesale rates with us; we resell.

---

## Core user stories

A developer writes a Python MCP server that wraps a paid SERP API. They run `agentgate publish`, choose "per-call pricing at $0.05 with $0.02 cost basis," upload credentials for their SERP provider, and within ten minutes have a public listing in the marketplace. When users invoke their server, AgentGate handles auth, rate limiting, billing, and pays them out monthly.

A user installs Claude Desktop, runs `agentgate connect`, and pastes a single config snippet. Claude now sees the AgentGate aggregator MCP server, which proxies to every server the user has subscribed to. Browsing the marketplace web UI, they click "subscribe" on a Postgres MCP, are walked through authenticating to their database once, and the tools become available in Claude immediately.

A user types "find me three real estate comps near 123 Main St" in Claude Desktop. Claude calls the `comp_search` tool exposed by a third-party MCP server hosted on AgentGate. AgentGate authenticates the user, checks their balance, places a billing hold, proxies the call to the running MCP server instance, settles the hold against the actual cost, and returns the result. The user never thinks about any of this.

A wholesale provider (e.g. Tavily) signs a contract for a wholesale rate of $0.04 per search call and gets onboarded as a managed source. AgentGate operates the MCP server, charges end users $0.10 per call, and reconciles the spread monthly.

---

## Pricing models we must support

The billing system has to be flexible enough for all four of these out of the box, because trying to force every server into one model will exclude half the market:

**Per-call metering.** Developer sets a price per `tools/call`, optionally per-tool (some calls cost more than others). Used for servers that wrap paid APIs.

**Flat subscription.** Fixed monthly fee for unlimited usage (with reasonable abuse limits). Used for servers where invocation count is noisy and the value is access, not usage. Hosting-heavy servers (browser automation, long-running scrapers) tend toward this.

**Freemium with paid tools.** The server exposes some tools for free (maybe rate-limited) and others as paid. Used for servers where the cheap operations are loss-leaders and the expensive ones (deep research, large model calls) are where the cost lives.

**Bring-your-own-credentials hosted.** The user provides credentials to the underlying service (Stripe, Linear, Postgres) and pays AgentGate a flat monthly fee for the convenience of managed hosting. Margin is thin but lock-in is high.

All four share a common substrate: prepaid credits, invocation-level metering, and monthly developer payouts. The differences are billing rules layered on top.

---

## Functional requirements (V1)

### Marketplace web app

Public-facing catalog with category browsing, search (semantic, by name, by capability), per-server detail pages including the tool schema, pricing, ratings, and install instructions. Developer dashboard for publishing, managing pricing, viewing invocation analytics, and configuring payouts. End-user dashboard for managing subscriptions, viewing usage, topping up balance, managing per-server credentials.

### MCP gateway

A single MCP server endpoint that the user connects to from their host client. It speaks the MCP protocol on the user side and aggregates every server the user has subscribed to, exposing all their tools as a flat namespace (with collision handling). On a tool call, it routes to the right backing server, handles auth and metering inline, and returns the response.

This is the central technical bet: **one connection per user, not one per server.** It dramatically reduces UX friction on the consumer side and gives us the chokepoint where we can meter and observe everything.

### Hosting runtime

Managed infrastructure to run developer-uploaded MCP servers. Supports Python and Node.js in V1. Servers are warm-started on first use per user, kept alive for a configurable idle period, and torn down. Memory and CPU limits enforced. Outbound network policy is open by default but loggable.

### Credential vault

Already exists in the current codebase (Fernet-encrypted credentials per agent). Extended to handle two distinct credential types: **developer credentials** (the API keys their server needs to do its job, set once at publish time) and **end-user credentials** (the user's own API keys to a service the server proxies, set per-subscription). The latter is a new concept and is the gnarliest part of the design.

### Billing engine

Already exists in current codebase (double-entry ledger, prepaid credits, Stripe deposits). Extended to support subscription billing, per-tool pricing within a server, and the four pricing models above. Monthly payout pipeline to developers via Stripe Connect.

### Discovery / registry

Semantic search over MCP server descriptions, tool schemas, and tags. Already exists in current codebase but needs the actual embedding pipeline working (currently broken — placeholder OpenAI key). Ranking signals: install count, retention, ratings, recency.

### Developer CLI

`agentgate publish`, `agentgate logs`, `agentgate test`, `agentgate version`. Single-command path from local Python file to live listing.

---

## Out of scope for V1

Enterprise SSO, SCIM, audit logs, VPC peering. White-label / private marketplaces. On-prem hosting. Multi-tenant key management for orgs. Compliance certifications beyond basic SOC2 readiness posture. We get to those when we have an enterprise pipeline asking for them.

---

## Success metrics

**North star:** Total monthly GMV flowing through AgentGate-hosted MCP servers.

**Supply side:** Number of paid MCP servers published per month. Time from signup to first published server. Developer revenue retention (do they stay listed?).

**Demand side:** Weekly active connected hosts. Number of tool calls per host per week. Free-to-paid conversion. ARPU among paying users.

**Marketplace health:** Search-to-install conversion. Install-to-first-call conversion. Per-server retention curves.

**Engineering health:** Tool-call latency p50/p99 (gateway round-trip including upstream MCP server). Hosting cost per million invocations. Cold-start latency for warm-pool misses.

---

## Wedge strategy

Marketplaces die in the cold-start phase. We don't try to be everything to everyone in V1. We pick a single user wedge and a single supply wedge that match.

**Demand wedge: power users of Claude Desktop and Claude Code who already pay for AI tooling.** This is the smallest possible audience that has both willingness to pay and immediate use for MCP. We acquire them through Claude Code CLAUDE.md snippets (which we already do for the agent product), Cursor and Claude integrations content, and a small but visible launch on Hacker News and the Anthropic Discord.

**Supply wedge: paid-API-resellers and developer-tooling MCPs.** Specifically: search APIs (Tavily, Exa, SerpAPI), database connectors (Postgres, MySQL, MongoDB), browser automation (Playwright, Puppeteer), and source-of-truth integrations (Linear, Notion, Jira). These are servers where the value is obvious, the pricing model is clean (per-call), and the user already understands why they'd pay.

**First 10 servers we ship at launch:** we build or commission these ourselves to seed the marketplace. They're loss leaders that demonstrate the four pricing models and prove the platform works end-to-end.

We do **not** chase social, calendar, email, or productivity-app MCPs in V1 — those have OAuth complexity and the platform owners are likely to ship native versions. We stay in the developer-tooling lane until we have liquidity, then expand.

---

## Risks

**Anthropic decides to host MCP servers themselves.** Mitigation: we move fast, we make ourselves protocol-neutral (we'll happily host MCP servers reachable from GPT, Cursor, and any future client), and we make the marketplace network the moat — by the time they decide, we have the developers and the discovery data. This is the same dynamic as Stripe vs. card networks, and it can work.

**Per-call MCP economics don't pencil out.** Many MCP calls are sub-cent in real cost. If the average revenue per call is $0.001 and our per-call infrastructure cost is $0.0005, the spread is too thin to support a real business. Mitigation: we lean toward subscription and freemium pricing for our own seeded servers and keep the per-call market for high-value tool calls only.

**Cold start failure.** If we can't get to liquidity before runway runs out, we die. Mitigation: the wedge strategy above; aggressive partnership outreach to wholesale API providers; willingness to be the publisher of last resort for the first 50 servers.

**Protocol churn.** MCP is young. A breaking change to the spec could force a reimplementation. Mitigation: implement the spec cleanly with a thin abstraction layer, stay close to the working group, contribute upstream when we hit pain.

**Trust and abuse.** A malicious MCP server could exfiltrate user credentials, abuse upstream APIs we host, or generate harmful content. Mitigation: review process for paid listings, sandboxed hosting with egress logging, scoped credential injection (servers never see end-user credentials directly — they request them through a typed API that can be audited).

---

## Open questions

How do we handle MCP servers that need long-lived connections (a watch on a Postgres table, a websocket to Slack)? The pure request/response gateway model doesn't fit cleanly. Probably needs a streaming variant of the gateway that holds connections open per-user.

What's the right policy on free servers? If we host them for free we eat cost; if we don't host them we lose discovery surface. Lean toward "free servers are listed and discoverable but not hosted by us — developer self-hosts and we proxy."

How do we handle the protocol's `roots` and `sampling` features which require the host to expose data back into the server's reasoning? These complicate the trust model significantly. V1 may simply not support sampling.

What's the take rate? Stripe is 2.9%, App Store is 30%, GPT Store is unclear. Initial proposal: 15% on per-call, 20% on subscription, 0% on BYO-credentials hosting (we charge a flat hosting fee instead). Revisit with data.

How do we handle credential rotation when a developer changes their backing API key? Need a non-breaking rotation flow.
