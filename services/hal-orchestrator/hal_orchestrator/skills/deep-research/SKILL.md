---
{
  "description": "Research a topic with cited sources. Returns 5 bullets + a verdict line, each bullet citing a domain.",
  "keywords": ["research", "deep dive", "look into", "what's the deal with", "find sources"],
  "inputs": [
    {"name": "topic", "description": "What to research", "required": true},
    {"name": "depth", "description": "'quick' (3 bullets) or 'deep' (5-7 bullets, default deep)", "required": false}
  ]
}
---

Research request: {{topic}}

Steps:

1. Delegate to the research agent with task = "research {{topic}} — return
   bullet points with cited sources (URL or domain)". Research handles
   web search + fact-checking + citation.
2. If research returns thin or fails, do the web pass yourself: several
   web_search queries from different angles + web_fetch the best results.
   Then add a note: "couldn't get deep sources — quick web pass instead".

Reply format (plain text, iMessage):

{{topic}}

- <claim> [source: domain.com]
- <claim> [source: domain.com]
- <claim> [source: domain.com]
- (4-7 bullets total for deep, 3 for quick)

Bottom line: <one sentence — your synthesized take. NOT just a restatement
of the bullets — your actual judgment on the question.>

Rules:
- Every bullet must have a [source: ...] tag. No source = don't include it.
- If sources conflict, say so explicitly: "sources disagree — X says A, Y says B"
- Keep each bullet under ~150 chars
- Total reply under ~1200 chars
