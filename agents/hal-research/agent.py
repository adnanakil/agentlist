"""hal-research — multi-step web research agent with Gemini tool-use loop."""

import json
import os
import re
import ssl
import urllib.parse
import urllib.request

from agentgate_sdk import AgentHandler, run_agent

try:
    import certifi
    _ssl_ctx = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _ssl_ctx = ssl.create_default_context()


def urlopen(req, **kw):
    return urllib.request.urlopen(req, context=_ssl_ctx, **kw)

DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

TOOLS = [
    {
        "function_declarations": [
            {
                "name": "web_search",
                "description": "Search the web using DuckDuckGo.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "web_fetch",
                "description": "Fetch and read the text content of a web page.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to fetch"},
                    },
                    "required": ["url"],
                },
            },
        ]
    }
]

SYSTEM_PROMPT = (
    "You are a Research Agent. You search the web and gather information.\n"
    "Your job is to research a topic and return a clear, concise summary.\n\n"
    "Use web_search to find information, then web_fetch to read promising pages.\n"
    "Cross-reference multiple sources for accuracy.\n"
    "Return factual, well-organized information. Be concise.\n"
    "No markdown formatting — plain text only.\n"
    "When done, return ONLY the answer — no meta-commentary about your research process."
)


def web_search(query: str) -> str:
    """Search DuckDuckGo HTML interface."""
    try:
        data = urllib.parse.urlencode({"q": query}).encode()
        req = urllib.request.Request(
            DUCKDUCKGO_HTML_URL,
            data=data,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp = urlopen(req, timeout=15)
        html = resp.read().decode("utf-8", errors="replace")

        snippets = re.findall(
            r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
            r'class="result__snippet"[^>]*>(.*?)</a>',
            html,
            re.DOTALL,
        )

        results = []
        for url, title, snippet in snippets[:5]:
            title = re.sub(r"<[^>]+>", "", title).strip()
            snippet = re.sub(r"<[^>]+>", "", snippet).strip()
            if title:
                results.append(f"{title}\n{snippet}\n{url}")

        if not results:
            return f"No results found for '{query}'."
        return "\n\n".join(results)
    except Exception as exc:
        return f"Search error: {exc}"


def web_fetch(url: str) -> str:
    """Fetch and extract text from a URL."""
    # Reddit blocks simple HTTP fetches; use old.reddit.com which serves static HTML
    if "reddit.com/" in url and "old.reddit.com" not in url:
        url = url.replace("www.reddit.com", "old.reddit.com").replace("://reddit.com", "://old.reddit.com")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urlopen(req, timeout=20)
        content_type = resp.headers.get("content-type", "")
        body = resp.read().decode("utf-8", errors="replace")

        if "text/html" in content_type:
            text = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 8000:
                text = text[:8000] + "... (truncated)"
            return text
        else:
            return body[:8000]
    except Exception as exc:
        return f"Fetch error: {exc}"


TOOL_HANDLERS = {
    "web_search": lambda args: web_search(args.get("query", "")),
    "web_fetch": lambda args: web_fetch(args.get("url", "")),
}


def call_gemini(api_key: str, model: str, history: list, system: str) -> dict | None:
    """Call Gemini with tool-use support."""
    url = f"{GEMINI_API_BASE}/{model}:generateContent?key={api_key}"
    payload = {
        "contents": history,
        "tools": TOOLS,
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048},
    }
    req = urllib.request.Request(
        url,
        json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urlopen(req, timeout=60)
        return json.loads(resp.read())
    except Exception:
        return None


class ResearchAgent(AgentHandler):
    def handle(self, input_data):
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            return {"error": "No GEMINI_API_KEY configured"}

        query = input_data.get("query", "")
        context = input_data.get("context", "")
        max_sources = input_data.get("max_sources", 5)

        if not query:
            return {"error": "query is required"}

        model = "gemini-2.0-flash"

        prompt = f"Research this: {query}"
        if context:
            prompt += f"\nContext: {context}"
        prompt += f"\nConsult up to {max_sources} sources."

        history = [{"role": "user", "parts": [{"text": prompt}]}]
        sources = []

        for iteration in range(10):
            response = call_gemini(api_key, model, history, SYSTEM_PROMPT)
            if response is None:
                return {"error": "Gemini API call failed", "query": query}

            candidates = response.get("candidates", [])
            if not candidates:
                return {"error": "No candidates returned", "query": query}

            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                return {"error": "Empty response", "query": query}

            func_calls = [p for p in parts if "functionCall" in p]

            if func_calls:
                history.append({"role": "model", "parts": parts})

                func_responses = []
                for fc in func_calls:
                    call = fc["functionCall"]
                    tool_name = call["name"]
                    tool_args = call.get("args", {})

                    handler = TOOL_HANDLERS.get(tool_name)
                    if handler:
                        result = handler(tool_args)
                        if tool_name == "web_fetch" and tool_args.get("url"):
                            sources.append(tool_args["url"])
                    else:
                        result = f"Unknown tool: {tool_name}"

                    func_responses.append({
                        "functionResponse": {
                            "name": tool_name,
                            "response": {"content": result},
                        }
                    })

                history.append({"role": "user", "parts": func_responses})
                continue

            # No function calls — extract final answer
            text_parts = [p.get("text", "") for p in parts if "text" in p]
            answer = "\n".join(text_parts).strip()

            return {
                "answer": answer,
                "sources": sources[:max_sources],
                "query": query,
                "iterations": iteration + 1,
            }

        return {
            "answer": "Research reached max iterations without completing.",
            "sources": sources[:max_sources],
            "query": query,
            "iterations": 10,
        }


if __name__ == "__main__":
    run_agent(ResearchAgent())
