"""hal-brainstorm — creative thinking and analysis agent powered by Gemini Pro."""

import json
import os
import ssl
import urllib.request

from agentgate_sdk import AgentHandler, run_agent

try:
    import certifi
    _ssl_ctx = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _ssl_ctx = ssl.create_default_context()


def urlopen(req, **kw):
    return urllib.request.urlopen(req, context=_ssl_ctx, **kw)


GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

STYLE_PROMPTS = {
    "divergent": (
        "Generate as many diverse, creative ideas as possible. "
        "Think wild, unconventional, and across different domains. "
        "Quantity over quality — we'll filter later."
    ),
    "convergent": (
        "Evaluate and refine the concept. Identify the strongest angles, "
        "potential pitfalls, and concrete next steps. Be critical but constructive."
    ),
    "reframe": (
        "Look at this from completely different perspectives. "
        "How would a child see it? An investor? An artist? A scientist? "
        "What assumptions are we making that we could challenge?"
    ),
    "freeform": (
        "Think freely and creatively about this topic. "
        "Mix practical ideas with imaginative ones. "
        "Make unexpected connections."
    ),
}


class BrainstormAgent(AgentHandler):
    def handle(self, input_data):
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            return {"error": "No GEMINI_API_KEY configured"}

        topic = input_data.get("topic", "")
        style = input_data.get("style", "freeform")
        num_ideas = input_data.get("num_ideas", 5)

        if not topic:
            return {"error": "topic is required"}

        style_instruction = STYLE_PROMPTS.get(style, STYLE_PROMPTS["freeform"])

        system = (
            "You are a Brainstorm Agent. You help with creative thinking, analysis, and ideation.\n"
            "When given a topic, provide thoughtful analysis, pros/cons, creative ideas, or strategic thinking.\n"
            "Be thorough but organized. No markdown formatting — plain text only.\n"
            "Think step by step and consider multiple angles.\n\n"
            f"{style_instruction}\n"
            f"Generate approximately {num_ideas} distinct ideas or angles."
        )

        model = "gemini-2.5-pro-preview-05-06"
        url = f"{GEMINI_API_BASE}/{model}:generateContent?key={api_key}"

        payload = {
            "contents": [{"role": "user", "parts": [{"text": topic}]}],
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {"temperature": 0.8, "maxOutputTokens": 2048},
        }

        req = urllib.request.Request(
            url,
            json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )

        try:
            resp = urlopen(req, timeout=90)
            data = json.loads(resp.read())
        except Exception as e:
            return {"error": f"Gemini API call failed: {e}"}

        candidates = data.get("candidates", [])
        if not candidates:
            return {"error": "No candidates returned", "topic": topic}

        parts = candidates[0].get("content", {}).get("parts", [])
        text_parts = [p.get("text", "") for p in parts if "text" in p]
        response_text = "\n".join(text_parts).strip()

        return {
            "response": response_text,
            "topic": topic,
            "style": style,
        }


if __name__ == "__main__":
    run_agent(BrainstormAgent())
