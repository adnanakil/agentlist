from pydantic_settings import BaseSettings


class BaseConfig(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://agentgate:agentgate@localhost:5432/agentgate"
    redis_url: str = "redis://localhost:6379/0"


class GatewayConfig(BaseConfig):
    registry_url: str = "http://localhost:8001"
    billing_url: str = "http://localhost:8002"
    orchestrator_url: str = "http://localhost:8003"
    rate_limit_per_minute: int = 100


class RegistryConfig(BaseConfig):
    openai_api_key: str = ""


class BillingConfig(BaseConfig):
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_success_url: str = "https://agentgate.com/billing/success"
    stripe_cancel_url: str = "https://agentgate.com/billing/cancel"


class OrchestratorConfig(BaseConfig):
    billing_url: str = "http://localhost:8002"
    agent_timeout_seconds: int = 300
    agent_memory_limit_mb: int = 512
    agent_cpu_limit: float = 1.0
    encryption_key: str = ""


class WebConfig(BaseConfig):
    session_secret: str = "change-me-in-production"
    encryption_key: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_verify_service_sid: str = ""
    hal_provision_secret: str = ""


class HalOrchestratorConfig(BaseConfig):
    gemini_api_key: str = ""
    # Anthropic key — set to run the main loop on a claude-* model (the call
    # layer routes any model id starting with "claude" through the Claude shim).
    anthropic_api_key: str = ""
    # GLM (Z.ai) — set ANY task's model id to "glm-*" (e.g. GEMINI_MODEL or
    # GEMINI_BACKGROUND_MODEL = glm-5.2) to route it through Z.ai's
    # Anthropic-compatible endpoint via the GLM shim (services/glm_provider.py).
    # Needs glm_api_key funded; the base URL rarely changes.
    glm_api_key: str = ""
    glm_base_url: str = "https://api.z.ai/api/anthropic"
    # OpenAI — set ANY task's model id to "gpt-*" (e.g. GEMINI_MODEL =
    # gpt-5.6-luna) to route it through the Responses-API shim
    # (services/openai_provider.py).
    openai_api_key: str = ""
    # OpenRouter — set ANY task's model id to an OpenRouter "vendor/model" id
    # (e.g. GEMINI_MODEL=moonshotai/kimi-k3) to route it through the
    # chat-completions shim (services/openrouter_provider.py). Any model id
    # containing "/" goes here; no native model id has one.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Reasoning depth for gpt-* models (none/low/medium/high/xhigh). Deliberately
    # NOT driven by gemini_thinking_level: pushing that global to MAX to get
    # frontier depth on OpenAI would also send thinkingLevel=MAX to the native
    # Gemini fallback, which rejects it — nulling the exact fallback that's
    # supposed to catch an OpenAI outage. An explicit per-call thinking_level
    # (e.g. the watch poll forcing MINIMAL) still overrides this.
    openai_reasoning_effort: str = "xhigh"
    gemini_model: str = "gemini-3.6-flash"  # MAIN user-facing agent loop
    # Resilience: if the MAIN loop's model fails (Anthropic 529 Overloaded, a
    # depleted-credits error, timeouts), try these models in order before giving
    # up — so one provider/model being down doesn't take HAL down. Comma-
    # separated, tried left to right. ONLY the main loop fails over (never the
    # cheap background model). claude-* entries run through the Anthropic shim,
    # gemini-* through the native path. Sonnet first = same-provider cover for an
    # Opus-only overload (no Gemini credits needed); Gemini = cross-provider
    # cover for an all-Anthropic outage (needs the Gemini key funded to fire).
    model_fallbacks: str = "claude-sonnet-4-6,gemini-3.1-pro-preview"
    gemini_flash_model: str = "gemini-3.6-flash"  # in-process specialist sub-agents
    # Always-on BACKGROUND machinery (heartbeat, nightly grading, self-critique)
    # — kept on a cheap model independent of the main loop, so a premium main
    # model (e.g. Claude Opus) only fires on real user messages, not the 24/7
    # heartbeat/grading/critic that otherwise dominate spend.
    gemini_background_model: str = "gemini-3.6-flash"
    # Thinking level for Gemini 3.5+ models. Valid: LOW, MEDIUM, HIGH, or empty
    # to disable. Empty/"NONE" → no thinkingConfig sent. Default MEDIUM gives a
    # nice quality boost without the latency of HIGH.
    gemini_thinking_level: str = "MEDIUM"
    # OVERSEER model — the judgment brain of the nightly growth loop (turn
    # grading, playbook synthesis, hypothesis verification, backlog specs) and
    # the system-health diagnosis. Runs once nightly over a bounded set of
    # turns, so a frontier model (claude-fable-5) is affordable exactly here —
    # where its judgment compounds into every prompt (playbook) and every
    # build spec. "" -> gemini_background_model.
    overseer_model: str = ""
    hal_bridge_secret: str = ""
    hal_bridge_url: str = ""
    orchestrator_url: str = "http://localhost:8005"
    max_tool_iterations: int = 15
    max_tool_calls_per_turn: int = 30
    max_specialist_iterations: int = 10
    max_conversation_turns: int = 40
    tool_timeout_seconds: int = 45
    turn_timeout_seconds: int = 240
    silo_concurrency_wait_seconds: int = 10
    max_message_chars: int = 12000
    max_images_per_message: int = 4
    max_image_base64_chars: int = 8_000_000
    max_request_bytes: int = 36_000_000
    gemini_timeout_seconds: int = 60
    gemini_temperature: float = 0.7
    # Shared budget for THINKING + visible output on Gemini thinking models.
    # Must be generous: with thinking_level HIGH, reasoning alone can exhaust a
    # small cap and truncate the answer mid-sentence (finishReason MAX_TOKENS).
    # It's a ceiling, not a target — you're billed for tokens actually used, so
    # a higher cap just prevents premature cutoff, it doesn't cost more on short
    # replies. Kept equal to the Claude/GLM shim default (16384) so a mid-turn
    # failover between providers never silently halves the output budget.
    gemini_max_output_tokens: int = 16384
    reminder_check_interval_seconds: int = 30
    gemini_image_model: str = "gemini-2.5-flash-image"
    # Cheap shallow model for watch polls (WATCH_FEATURE_SPEC.md). Forced to
    # thinkingLevel=MINIMAL per-call so a silent high-frequency poll never runs
    # the full pro pipeline.
    gemini_watch_model: str = "gemini-3.1-flash-lite"
    watch_check_interval_seconds: int = 60
    watch_max_per_silo: int = 3
    # Self-critique pass on plan/recommendation turns (hardening "Layer 2").
    # One extra no-tools model call on gated turns only; kill with =false.
    critic_enabled: bool = True
    browser_service_url: str = ""
    # Shared secret for the browser service's /scrape and browser-action APIs.
    scraper_api_key: str = ""
    # Skills curator settings. interval=0 disables; default weekly.
    curator_check_interval_seconds: int = 60 * 30  # how often loop wakes
    curator_interval_hours: int = 24 * 7  # min hours between actual passes
    curator_min_idle_seconds: int = 60 * 60 * 2  # require this much quiet first
    curator_auto_apply: bool = True  # apply archive recommendations automatically
    curator_enabled: bool = True
    agentlist_orchestrator_url: str = ""  # e.g. "http://orchestrator.railway.internal:8003"
    agentlist_gateway_url: str = ""       # fallback: "https://gateway-production-cd14.up.railway.app"
    agentlist_api_key: str = ""           # Bearer token for gateway fallback
    agentlist_account_id: str = ""        # UUID for internal invoke X-Account-ID header
    rapidapi_key: str = ""                # RapidAPI key for Airbnb search
    # Instacart developer key (https://docs.instacart.com) for the grocery tool.
    # Unset -> the tool returns a graceful "not set up yet" message, never an error.
    instacart_api_key: str = ""
    # Amazon Associates tag for the grocery tool's add-to-cart links. When set,
    # it's appended as the documented AssociateTag param on the cart URL; when
    # empty the param is omitted entirely (see PA-API "Add to Cart form").
    amazon_associate_tag: str = ""
    # Brave Search API key (https://brave.com/search/api). When set, web_search
    # uses Brave (reliable JSON API) and falls back to DuckDuckGo scraping only
    # if Brave errors. Unset -> DDG scraping (brittle: bot-blocked pages).
    brave_search_api_key: str = ""
    # Google Routes API key (travel_time tool: live-traffic drive times,
    # walking, transit with real schedules).
    google_maps_api_key: str = ""
    # Apple ID that HAL users share their location with in Find My. Surfaced in
    # the one-time "share your location with HAL" invitation when a live-location
    # turn arrives from someone the Mac bridge couldn't find in its roster.
    findmy_share_handle: str = "hal_msg@icloud.com"
    # Heartbeat: per-silo anticipation checks ("is anything coming up, and did
    # the world change under it?"). Runs a silent internal agent turn per
    # recently-active silo every interval; texts only when genuinely useful.
    heartbeat_enabled: bool = True
    heartbeat_interval_minutes: int = 15
    heartbeat_activity_window_hours: int = 48
    heartbeat_active_hour_start: int = 7   # local (USER_TZ) hour, inclusive
    heartbeat_active_hour_end: int = 22    # local hour, exclusive
    heartbeat_include_groups: bool = False  # group tools can't see calendar/gmail
    heartbeat_max_silos_per_tick: int = 10
    # Hard floor between proactive contacts per silo: if HAL texted this silo
    # unprompted (heartbeat/reminder/cron/brief/follow-up) within this window,
    # the next heartbeat SKIPS instead of piling on — the deterministic fix
    # for the 15-near-identical-sends bursts that content-similarity gates
    # kept missing. A deterministic delivery alert still bypasses it.
    heartbeat_alert_cooldown_minutes: int = 60
    # Post-event follow-up sweep: after an event HAL helped plan has happened,
    # one low-key "how did it go?" and (days later) one "want to do something
    # like it again?" — model-gated, groups included, mute-respecting. OFF by
    # default: flip FOLLOWUP_ENABLED=true only after reviewing the dry-run
    # behavior, so a deploy never starts proactively texting unreviewed.
    followup_enabled: bool = False
    followup_interval_minutes: int = 45
    # Comma-separated silo allowlist for the sweep ("" = all active silos).
    # Lets follow-ups run in e.g. the owner's own DMs before group chats with
    # other people get proactive texts: FOLLOWUP_SILOS="+12015551234".
    followup_silos: str = ""
    # Base URL of the Ephemera NYC events engine (nyc_events tool). On Railway
    # same-project private networking: http://ephemera.railway.internal:{port}.
    # Unset -> the tool reports itself unavailable.
    ephemera_url: str = ""
    # Helpful mode: an OPT-IN proactive concierge (distinct from the heartbeat).
    # Once a day it sends a short brief tailored to the user's situation +
    # location (weather, local events, news, today's agenda), plus a few capped
    # same-day "something changed" pings. Per-user opt-in lives in
    # profile.extra_data["helpful"]; this is the master switch + cadence ceilings.
    helpful_enabled: bool = True
    helpful_model: str = ""                  # "" -> gemini_background_model
    helpful_check_interval_seconds: int = 300
    helpful_brief_hour: int = 8              # default local hour for the daily brief
    helpful_brief_window_hours: int = 3      # fire the brief only within [hour, hour+N) — never the evening
    helpful_active_hour_end: int = 21        # no pings after this local hour
    helpful_max_pings_per_day: int = 2       # opportunistic same-day pings (excl. brief)
    helpful_ping_min_gap_hours: int = 3      # min spacing between opportunistic checks
    # Google OAuth (per-user read-only Calendar + Gmail). client_id/secret come
    # from a Google Cloud OAuth 2.0 Web client; redirect_uri must be registered
    # on that client and point at this service's public /api/google/callback.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""
    # Fernet key (urlsafe-base64 of 32 bytes) for encrypting OAuth tokens at rest.
    encryption_key: str = ""
    # Where the nightly self-improvement digest (feature proposals) is sent.
    admin_phone: str = ""
    # HAL's public iMessage number, shown on the texthal.com landing page ("/").
    # Unset -> the page shows a coming-soon variant without a number.
    hal_public_number: str = ""
    # Separate purpose-bound key for public card links. Production refuses to
    # boot without it, so leaking a card URL cannot expose the bridge API key.
    card_signing_key: str = ""
    card_url_ttl_seconds: int = 15 * 60
    # Resy private-API web key (swappable without redeploy if Resy rotates it).
    # Defaults to Resy's public website key.
    resy_api_key: str = "VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"
    # Public base URL of this service (for the Resy connect web form link).
    public_base_url: str = "https://hal-orchestrator-production.up.railway.app"

    # --- Security / privacy hardening ------------------------------------- #
    # Dedicated token for the read-only /admin dashboard. Keep it DISTINCT from
    # hal_bridge_secret so a leaked admin URL (query strings land in proxy/access
    # logs) can't be replayed as bridge auth. Falls back to hal_bridge_secret
    # only when unset, to preserve existing single-secret deploys.
    admin_token: str = ""
    # SSRF guard: web_fetch / browser refuse URLs that resolve to loopback,
    # private, link-local, or reserved IP space (cloud metadata, *.internal
    # Railway hosts, localhost). Set true ONLY for a trusted single-tenant
    # self-host where reaching internal hosts is intended.
    allow_private_network_fetch: bool = False
    # Privacy: when false (default in production), operational logs omit the
    # actual text of user messages, memories, reminders, and outbound sends —
    # only lengths/metadata are logged. Flip true locally to debug content.
    log_message_content: bool = False
    # api = no proactive loops, worker = loops only, all = backwards-compatible
    # single-process deployment. A database advisory lock ensures one leader.
    hal_process_role: str = "all"
    worker_leader_lock_enabled: bool = True
    # Global playbook/skills are quarantined by default. This escape hatch is
    # intended only for a reviewed single-user deployment.
    growth_auto_publish: bool = False

    # --- Per-user message quota (free tier -> paid) ----------------------- #
    # Free user-initiated messages per calendar month, per 1:1 silo. Over the
    # cap, HAL replies with the funding message instead of running the model.
    # Heartbeats/proactive turns and group chats are never metered. 0 = no cap
    # (unlimited — the pre-billing default). A paid user's profile plan overrides
    # this (services/usage.py). Reset is by calendar month (UTC).
    free_message_limit: int = 0
    # Funding link shown when a user hits the cap — a Stripe Checkout / payment
    # link URL. On an iPhone this surfaces Apple Pay as a one-tap option in the
    # browser. Unset -> a graceful "coming soon" message with no link.
    payment_url: str = ""
    # Stripe webhook signing secret (whsec_...) for POST /api/stripe/webhook.
    # Set it to auto-unlock a user the moment they pay (checkout.session.completed
    # → lift their cap). Unset -> the webhook 503s and you unlock manually via
    # /api/admin/grant. The pay link carries a signed client_reference_id that
    # binds the payment back to the silo (see services/billing.py).
    stripe_webhook_secret: str = ""
    # Stripe secret key (sk_...) — only needed if you later create dynamic
    # per-user checkout sessions via the API. The payment-link flow doesn't use it.
    stripe_secret_key: str = ""
