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
from urllib.error import HTTPError


def urlopen(req, **kw):
    return _urlopen(req, context=_ssl_ctx, **kw)


BASE_URL = os.environ.get("HAL_PAGES_URL", "https://www.halnotes.xyz")


def api_request(method, path, body=None, query=None, secret=""):
    url = BASE_URL + path
    if query:
        url += "?" + "&".join(f"{k}={v}" for k, v in query.items())

    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")

    resp = urlopen(req, timeout=15)
    return json.loads(resp.read().decode())


class PageCreatorAgent(AgentHandler):
    def handle(self, input_data):
        secret = os.environ.get("PAGES_SECRET", "")
        if not secret:
            return {"error": "No PAGES_SECRET configured"}

        action = input_data.get("action", "create")
        title = input_data.get("title", "")
        content = input_data.get("content", "")
        page_id = input_data.get("page_id", "")

        try:
            if action == "create":
                if not title or not content:
                    return {"error": "title and content are required for create"}
                result = api_request("POST", "/api/pages", {
                    "title": title,
                    "content": content,
                    "secret": secret,
                })
                return result

            elif action == "update":
                if not page_id:
                    return {"error": "page_id is required for update"}
                body = {"secret": secret}
                if title:
                    body["title"] = title
                if content:
                    body["content"] = content
                result = api_request("PATCH", f"/api/pages/{page_id}", body)
                return result

            elif action == "list":
                result = api_request("GET", "/api/pages", query={
                    "secret": secret,
                })
                return result

            elif action == "delete":
                if not page_id:
                    return {"error": "page_id is required for delete"}
                result = api_request(
                    "DELETE", f"/api/pages/{page_id}", {"secret": secret}
                )
                return result

            else:
                return {"error": f"Unknown action: {action}"}

        except HTTPError as e:
            err_body = e.read().decode() if e.fp else str(e)
            return {"error": f"HTTP {e.code}: {err_body}"}
        except Exception as e:
            return {"error": str(e)}


if __name__ == "__main__":
    run_agent(PageCreatorAgent())
