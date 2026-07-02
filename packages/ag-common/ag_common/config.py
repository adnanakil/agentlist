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
    gemini_model: str = "gemini-3.5-flash"  # MAIN user-facing agent loop
    # Resilience: if the MAIN loop's model fails (Anthropic 529 Overloaded, a
    # depleted-credits error, timeouts), try these models in order before giving
    # up — so one provider/model being down doesn't take HAL down. Comma-
    # separated, tried left to right. ONLY the main loop fails over (never the
    # cheap background model). claude-* entries run through the Anthropic shim,
    # gemini-* through the native path. Sonnet first = same-provider cover for an
    # Opus-only overload (no Gemini credits needed); Gemini = cross-provider
    # cover for an all-Anthropic outage (needs the Gemini key funded to fire).
    model_fallbacks: str = "claude-sonnet-4-6,gemini-3.1-pro-preview"
    gemini_flash_model: str = "gemini-3.5-flash"  # in-process specialist sub-agents
    # Always-on BACKGROUND machinery (heartbeat, nightly grading, self-critique)
    # — kept on a cheap model independent of the main loop, so a premium main
    # model (e.g. Claude Opus) only fires on real user messages, not the 24/7
    # heartbeat/grading/critic that otherwise dominate spend.
    gemini_background_model: str = "gemini-3.5-flash"
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
    max_specialist_iterations: int = 10
    max_conversation_turns: int = 40
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
    # Brave Search API key (https://brave.com/search/api). When set, web_search
    # uses Brave (reliable JSON API) and falls back to DuckDuckGo scraping only
    # if Brave errors. Unset -> DDG scraping (brittle: bot-blocked pages).
    brave_search_api_key: str = ""
    # Google Routes API key (travel_time tool: live-traffic drive times,
    # walking, transit with real schedules).
    google_maps_api_key: str = ""
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
    # HAL's public iMessage number, shown on the tryhal.com landing page ("/").
    # Unset -> the page shows a coming-soon variant without a number.
    hal_public_number: str = ""
    # Resy private-API web key (swappable without redeploy if Resy rotates it).
    # Defaults to Resy's public website key.
    resy_api_key: str = "VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"
    # Public base URL of this service (for the Resy connect web form link).
    public_base_url: str = "https://hal-orchestrator-production.up.railway.app"
