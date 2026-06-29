import json
import os
import ssl
from agentgate_sdk import AgentHandler, run_agent

try:
    import certifi
    _ssl_ctx = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _ssl_ctx = ssl.create_default_context()

from urllib.request import Request, urlopen as _urlopen


def urlopen(req, **kw):
    return _urlopen(req, context=_ssl_ctx, **kw)


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
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {"error": "No ANTHROPIC_API_KEY configured"}

        topic = input_data.get("topic", "")
        style = input_data.get("style", "freeform")
        num_ideas = input_data.get("num_ideas", 5)

        if not topic:
            return {"error": "topic is required"}

        style_instruction = STYLE_PROMPTS.get(style, STYLE_PROMPTS["freeform"])

        system = (
            "You are a creative brainstorming partner. "
            "Your job is to help people think through ideas, problems, and opportunities. "
            f"{style_instruction} "
            f"Generate approximately {num_ideas} distinct ideas or angles. "
            "Format your response as a JSON object with: "
            "'ideas' (array of objects with 'title' and 'description'), "
            "'theme' (overall theme you noticed), "
            "and 'next_steps' (array of suggested actions)."
        )

        url = "https://api.anthropic.com/v1/messages"
        payload = {
            "model": "claude-sonnet-4-5-20250929",
            "max_tokens": 2048,
            "temperature": 0.8,
            "system": system,
            "messages": [{"role": "user", "content": topic}],
        }
        req = Request(url, json.dumps(payload).encode(), headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        })

        try:
            resp = urlopen(req, timeout=60)
            data = json.loads(resp.read())
        except Exception as e:
            return {"error": f"API call failed: {e}"}

        text = data["content"][0]["text"] if data.get("content") else ""

        # Try to parse as JSON, fall back to raw text
        try:
            result = json.loads(text)
            result["topic"] = topic
            result["style"] = style
            return result
        except (json.JSONDecodeError, ValueError):
            return {
                "topic": topic,
                "style": style,
                "response": text,
                "model": data.get("model", ""),
            }


if __name__ == "__main__":
    run_agent(BrainstormAgent())
