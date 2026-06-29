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


class InstacartListAgent(AgentHandler):
    def handle(self, input_data):
        api_key = os.environ.get("INSTACART_API_KEY", "")
        if not api_key:
            return {"error": "No INSTACART_API_KEY configured"}

        items = input_data.get("items", "")
        title = input_data.get("title", "Shopping List")

        if not items:
            return {"error": "items is required"}

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "create-shopping-list",
                "arguments": {"title": title, "items": items},
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
                "items": items,
                "result": data,
            }
        except Exception as e:
            return {"error": f"Instacart API call failed: {e}"}


if __name__ == "__main__":
    run_agent(InstacartListAgent())
