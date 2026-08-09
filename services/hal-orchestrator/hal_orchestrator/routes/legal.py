# ruff: noqa: E501 -- embedded policy HTML stays readable as authored markup.
"""GET /privacy and /terms — hosted legal pages on the app domain.

Google OAuth verification requires a publicly reachable privacy policy on a
domain you own (the consent screen links to it), and it must disclose how the
app uses Google user data, including the exact Limited Use affirmation. These
pages satisfy that. Served by the orchestrator so they resolve at both the
Railway URL and the custom domain once it's attached.

REVIEW BEFORE SUBMITTING FOR VERIFICATION: confirm the operator legal name,
contact email, and governing-law state (search for TODO markers below). Have a
lawyer glance at these — they are a solid, accurate starting draft, not legal
advice.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from hal_orchestrator.state import get_settings

# TODO(owner): replace with your legal name or LLC once formed, a working
# contact inbox, and your governing-law state.
OPERATOR = "HAL"
CONTACT_EMAIL = "privacy@texthal.com"
GOVERNING_LAW = "the United States"
LAST_UPDATED = "July 30, 2026"

# The exact affirmation Google's verification looks for.
LIMITED_USE = (
    "HAL's use and transfer to any other app of information received from Google "
    "APIs will adhere to the "
    '<a href="https://developers.google.com/terms/api-services-user-data-policy">'
    "Google API Services User Data Policy</a>, including the Limited Use requirements."
)


def _shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — HAL</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ background:#0a0a0c; color:#e8e8ea; margin:0;
    font:16px/1.6 -apple-system, BlinkMacSystemFont, system-ui, sans-serif; }}
  .wrap {{ max-width:760px; margin:0 auto; padding:48px 22px 80px; }}
  h1 {{ font-size:28px; letter-spacing:-.02em; margin:0 0 4px; }}
  h2 {{ font-size:19px; margin:34px 0 8px; }}
  .upd {{ color:#8b8b93; font-size:14px; margin-bottom:8px; }}
  p, li {{ color:#c7c7cf; }}
  a {{ color:#34c759; }}
  ul {{ padding-left:20px; }}
  .mark {{ font-size:13px; font-weight:600; letter-spacing:.42em; text-indent:.42em;
    color:#8b8b93; text-transform:uppercase; margin-bottom:24px; }}
  footer {{ margin-top:48px; color:#6b6b73; font-size:13px; }}
  footer a {{ color:#8b8b93; }}
</style></head>
<body><div class="wrap">
<div class="mark">HAL</div>
{body}
<footer>© {LAST_UPDATED[-4:]} {OPERATOR} · <a href="/privacy">Privacy</a> · <a href="/terms">Terms</a></footer>
</div></body></html>"""


def _privacy_html() -> str:
    body = f"""
<h1>Privacy Policy</h1>
<div class="upd">Last updated: {LAST_UPDATED}</div>
<p>HAL is a personal assistant you use over text message. This policy explains
what information HAL ("we", "us") collects, how we use and protect it, and the
choices you have. By texting HAL or connecting an account, you agree to this policy.</p>

<h2>Information we collect</h2>
<ul>
<li><b>Messages you send HAL</b> and HAL's replies, so HAL can help you and remember context.</li>
<li><b>Basic profile details</b> you tell HAL (e.g. your name, timezone, home/work area, saved contacts) and things you ask HAL to remember.</li>
<li><b>Your phone number / handle</b>, used as your account identifier.</li>
<li><b>Google account data</b>, only if you choose to connect Google (see below).</li>
<li><b>Billing information</b> is handled by our payment processor (Stripe); we do not store your card details.</li>
</ul>

<h2>Google user data</h2>
<p>Connecting Google is optional and done from your own chat with HAL. If you connect, HAL requests only the access needed for the features you use:</p>
<ul>
<li><b>Google Calendar</b> (read and create events) — to check your schedule and add events when you ask.</li>
</ul>
<p>HAL uses this data solely to provide these features to you, in response to your requests. We do <b>not</b> sell Google user data, use it for advertising, or use it to train generalized AI/ML models.</p>
<p>{LIMITED_USE}</p>

<h2>How we use your information</h2>
<ul>
<li>To understand your requests and respond helpfully.</li>
<li>To remember context and preferences so HAL improves over time for you.</li>
<li>To send timely, useful proactive messages (which you can turn off).</li>
<li>To operate, secure, and improve the service, and to process payments.</li>
</ul>

<h2>How your information is shared</h2>
<p>We share data only with service providers who process it on our behalf to run
HAL, under confidentiality obligations — not for their own purposes:</p>
<ul>
<li><b>AI model providers</b> (e.g. Google Gemini, Anthropic) process the content of your requests to generate HAL's responses. These providers do not use API data to train their models.</li>
<li><b>Infrastructure</b> (Railway) for hosting and our database.</li>
<li><b>Payments</b> (Stripe) to process subscriptions.</li>
<li><b>Look-up services</b> you trigger (e.g. web search, maps, weather) receive only what's needed to answer that request.</li>
</ul>
<p>We may also disclose information if required by law, or to protect the rights and safety of our users. We do not sell your personal information.</p>

<h2>Data retention and deletion</h2>
<p>You are in control of your data:</p>
<ul>
<li>Text <b>"/clear"</b> to erase your current conversation history.</li>
<li>Text HAL <b>"disconnect google"</b> to immediately revoke and delete your stored Google tokens.</li>
<li>Email <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a> to request deletion of your account and all associated data. We honor deletion requests promptly.</li>
</ul>
<p>We retain data only as long as needed to provide the service or as required by law.</p>

<h2>Security</h2>
<p>Access tokens for connected accounts are encrypted at rest (AES-256). Data is
transmitted over encrypted connections (TLS). Each user's data is siloed so it is
not accessible to other users. No system is perfectly secure, but we take
reasonable measures to protect your information.</p>

<h2>Children</h2>
<p>HAL is not directed to children under 13 (or the minimum age in your country), and we do not knowingly collect their data.</p>

<h2>Changes to this policy</h2>
<p>We may update this policy; material changes will be reflected by the "last updated" date above.</p>

<h2>Contact</h2>
<p>Questions or requests: <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>.</p>
"""
    return _shell("Privacy Policy", body)


def _terms_html() -> str:
    body = f"""
<h1>Terms of Service</h1>
<div class="upd">Last updated: {LAST_UPDATED}</div>
<p>These terms govern your use of HAL. By texting HAL, you agree to them.</p>

<h2>The service</h2>
<p>HAL is a personal assistant you interact with over text message. It can answer
questions, run tasks, set reminders, and — if you connect Google — help with your
calendar. HAL is an automated assistant and can make mistakes; use
judgment before relying on its output for anything important.</p>

<h2>Eligibility</h2>
<p>You must be at least 18 (or the age of majority where you live) to use HAL.</p>

<h2>Plans and billing</h2>
<ul>
<li>HAL offers a free tier with a monthly message limit. Beyond it, a paid subscription is available.</li>
<li>Subscriptions are billed through Stripe on a recurring basis until cancelled.</li>
<li>You can cancel anytime; access continues through the current billing period, after which you return to the free tier.</li>
</ul>

<h2>Acceptable use</h2>
<p>Don't use HAL to break the law, harm others, send spam or unsolicited messages, infringe others' rights, or attempt to disrupt or reverse-engineer the service.</p>

<h2>Google services</h2>
<p>If you connect Google, your use of Google data through HAL is also governed by our <a href="/privacy">Privacy Policy</a> and Google's terms. You can disconnect at any time.</p>

<h2>Disclaimers and liability</h2>
<p>HAL is provided "as is", without warranties of any kind. To the fullest extent
permitted by law, we are not liable for indirect, incidental, or consequential
damages, and our total liability is limited to the amount you paid us in the
prior three months.</p>

<h2>Termination</h2>
<p>You may stop using HAL at any time. We may suspend or terminate access for violation of these terms.</p>

<h2>Governing law</h2>
<p>These terms are governed by the laws of {GOVERNING_LAW}.</p>

<h2>Contact</h2>
<p><a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>.</p>
"""
    return _shell("Terms of Service", body)


def build_legal_router() -> APIRouter:
    router = APIRouter()

    @router.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
    async def privacy() -> HTMLResponse:
        get_settings()  # ensure settings load; content is static
        return HTMLResponse(_privacy_html())

    @router.get("/terms", response_class=HTMLResponse, include_in_schema=False)
    async def terms() -> HTMLResponse:
        return HTMLResponse(_terms_html())

    return router
