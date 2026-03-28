---
name: dispatch-api
description: "Invoke this skill using the Skill tool whenever the user asks to use Dispatch, arXiv, Zillow, Instacart, Amazon, LinkedIn, SEC filings, flights, Yelp, Google Workspace, medical codes, scholarly research, brainstorming, image generation, web scraping, or any task that requires calling an external agent API. This skill provides the Dispatch agent marketplace API which has 20+ pre-built agents accessible via curl."
---

# Dispatch — Agent Marketplace

You have access to Dispatch, a hosted agent marketplace with 20+ pre-built AI agents. Use it to delegate specialized tasks (research, shopping, travel, finance, etc.) to purpose-built agents via a single API.

## Setup — IMPORTANT: Read before first use

Before making any Dispatch API call, you MUST have an API key. Check for one in this order:

1. Check if `${user_config.DISPATCH_API_KEY}` is set and not empty/placeholder.
2. If not, read `~/.claude/settings.json` and look for `pluginConfigs.dispatch@dispatch-marketplace.options.DISPATCH_API_KEY`.
3. If no key is found, **ask the user**:

> "To use Dispatch agents, I need your API key. You can get one at https://web-production-f1dbe.up.railway.app/signup — paste it here and I'll save it for future sessions."

Once the user provides the key, save it by editing `~/.claude/settings.json` — add or update the `pluginConfigs` section:

```json
{
  "pluginConfigs": {
    "dispatch@dispatch-marketplace": {
      "options": {
        "DISPATCH_API_KEY": "THE_KEY_THEY_GAVE_YOU"
      }
    }
  }
}
```

Then use that key for all API calls in this session.

## API Access

- **Gateway URL:** `https://gateway-production-cd14.up.railway.app`
- **API Key:** Use the key from setup above.

## Available Agents

| Agent | Price | Description |
|-------|-------|-------------|
| `zillow-research` | 10c | Search Zillow listings, pull comps, tax & price history, valuation analysis |
| `instacart-list` | 5c | Build grocery lists with real-time Instacart availability and pricing |
| `instacart-recipe` | 5c | Find recipes and generate ingredient lists from Instacart |
| `amazon-research` | 8c | Search Amazon products, compare prices, analyze reviews, track price history |
| `arxiv-research` | 5c | Search arXiv papers, get AI summaries, extract key results, find related work |
| `medical-codes` | 3c | Look up ICD-10/CPT codes, billing guidance, modifier suggestions |
| `google-workspace` | 5c | Create/edit Google Docs, Sheets, Slides; read calendar; manage Gmail drafts |
| `linkedin-research` | 10c | Research companies and people on LinkedIn — employees, funding, jobs, org structure |
| `flight-search` | 8c | Search flights, compare fares, find layovers, track price drops |
| `sec-filings` | 10c | Search SEC EDGAR filings, extract financials from 10-K/10-Q, summarize risk factors |
| `github-analyzer` | 5c | Analyze repos, audit dependencies, review PRs, summarize changelogs |
| `yelp-search` | 5c | Search Yelp restaurants/businesses, read reviews, compare ratings, get menus |
| `scholar` | 5c | Search academic papers across sources, summarize findings |
| `brainstorm` | 3c | Generate creative ideas and structured brainstorms on any topic |
| `image-generator` | 10c | Generate images from text descriptions |
| `place-finder` | 5c | Find places, restaurants, attractions with detailed info |
| `page-creator` | 5c | Generate HTML pages from descriptions |
| `web-scraper` | 3c | Scrape and extract content from web pages |
| `claude-assistant` | 5c | General-purpose Claude assistant for text tasks |

## Endpoints

### Discover agents

Find agents by keyword or description:

```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "search term"}' \
  https://gateway-production-cd14.up.railway.app/v1/discover
```

### Invoke an agent

Run an agent with input:

```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"agent_slug": "agent-name", "input": {"message": "your request"}}' \
  https://gateway-production-cd14.up.railway.app/v1/invoke
```

The response includes `output`, `duration_ms`, and `price_cents`.

### Check balance

```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
  https://gateway-production-cd14.up.railway.app/v1/balance
```

## Usage Guidelines

1. **Check balance first** if the user hasn't used Dispatch before in this session, so they know their remaining credits.
2. **Use `/v1/discover`** when you're unsure which agent fits — search by keyword to find the best match.
3. **Use `/v1/invoke` directly** when you know the right agent slug from the table above.
4. **Show the cost** to the user before invoking if the task will use an expensive agent (8c+) or require multiple calls.
5. **Parse the response** and present results clearly — don't just dump raw JSON.
6. Agents are billed per invocation from the user's prepaid USD credit balance.
