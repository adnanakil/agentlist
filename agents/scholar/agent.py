import json
import os
import re
import ssl
from agentgate_sdk import AgentHandler, run_agent

try:
    import certifi
    _ssl_ctx = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _ssl_ctx = ssl.create_default_context()

from urllib.request import Request, urlopen as _urlopen
from urllib.parse import quote_plus


def urlopen(req, **kw):
    return _urlopen(req, context=_ssl_ctx, **kw)


def search_web(query, num_results=10):
    """Search using Google Custom Search API or fall back to a simple scrape."""
    api_key = os.environ.get("GOOGLE_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
    cx = os.environ.get("GOOGLE_SEARCH_CX", "")

    if api_key and cx:
        url = (
            f"https://www.googleapis.com/customsearch/v1"
            f"?key={api_key}&cx={cx}&q={quote_plus(query)}&num={num_results}"
        )
        req = Request(url, headers={"Accept": "application/json"})
        resp = urlopen(req, timeout=15)
        data = json.loads(resp.read())
        results = []
        for item in data.get("items", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })
        return results

    # Fallback: use Google Scholar scraping via SerpAPI if available
    serp_key = os.environ.get("SERPAPI_KEY", "")
    if serp_key:
        url = (
            f"https://serpapi.com/search.json"
            f"?engine=google_scholar&q={quote_plus(query)}"
            f"&api_key={serp_key}&num={num_results}"
        )
        req = Request(url, headers={"Accept": "application/json"})
        resp = urlopen(req, timeout=15)
        data = json.loads(resp.read())
        results = []
        for item in data.get("organic_results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "authors": item.get("publication_info", {}).get("summary", ""),
                "cited_by": item.get("inline_links", {}).get("cited_by", {}).get("total", 0),
            })
        return results

    return [{"error": "No search API key configured (GOOGLE_API_KEY+GOOGLE_SEARCH_CX or SERPAPI_KEY)"}]


class ScholarAgent(AgentHandler):
    def handle(self, input_data):
        query = input_data.get("query", "")
        max_sources = input_data.get("max_sources", 5)

        if not query:
            return {"error": "query is required"}

        # Search for academic sources
        scholar_query = f"{query} site:pubmed.ncbi.nlm.nih.gov OR site:nature.com OR site:science.org OR site:thelancet.com OR site:nejm.org"
        results = search_web(scholar_query, num_results=max_sources)

        # Also do a general search for broader context
        general_results = search_web(f"{query} research study findings", num_results=max_sources)

        # Combine and deduplicate
        seen_urls = set()
        all_results = []
        for r in results + general_results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)

        sources = all_results[:max_sources]

        return {
            "query": query,
            "sources": sources,
            "source_count": len(sources),
            "note": "Results are from web search. Verify claims against original papers.",
        }


if __name__ == "__main__":
    run_agent(ScholarAgent())
