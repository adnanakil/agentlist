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


class InstacartRecipeAgent(AgentHandler):
    def handle(self, input_data):
        api_key = os.environ.get("INSTACART_API_KEY", "")
        if not api_key:
            return {"error": "No INSTACART_API_KEY configured"}

        title = input_data.get("title", "")
        ingredients = input_data.get("ingredients", "")
        instructions = input_data.get("instructions", "")

        if not title or not ingredients:
            return {"error": "title and ingredients are required"}

        arguments = {"title": title, "ingredients": ingredients}
        if instructions:
            arguments["instructions"] = instructions

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "create-recipe",
                "arguments": arguments,
            },
            "id": 1,
        }

        req = Request(
            "https://mcp.instacart.com/mcp",
            json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json, text/event-stream",
            },
        )

        try:
            resp = urlopen(req, timeout=30)
            data = json.loads(resp.read())
            return {
                "title": title,
                "ingredients": ingredients,
                "instructions": instructions,
                "result": data,
            }
        except Exception as e:
            return {"error": f"Instacart API call failed: {e}"}


if __name__ == "__main__":
    run_agent(InstacartRecipeAgent())
