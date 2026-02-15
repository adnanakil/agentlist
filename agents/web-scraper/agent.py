import urllib.request
import html.parser
from agentgate_sdk import AgentHandler, run_agent


class SimpleHTMLParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.links = []
        self.title = ""
        self._in_title = False
        self._skip_tags = {"script", "style", "noscript"}
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            for attr_name, attr_val in attrs:
                if attr_name == "href" and attr_val:
                    self.links.append(attr_val)

    def handle_endtag(self, tag):
        if tag in self._skip_tags and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        text = data.strip()
        if text:
            if self._in_title:
                self.title = text
            self.text_parts.append(text)


class WebScraperAgent(AgentHandler):
    def handle(self, input_data):
        url = input_data["url"]

        req = urllib.request.Request(url, headers={"User-Agent": "AgentGate-WebScraper/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8", errors="replace")

        parser = SimpleHTMLParser()
        parser.feed(content)

        text = "\n".join(parser.text_parts)
        # Truncate to 50k chars to stay within reasonable output size
        if len(text) > 50000:
            text = text[:50000] + "\n... (truncated)"

        return {
            "title": parser.title,
            "text": text,
            "links": parser.links[:100],
            "content_length": len(content),
        }


if __name__ == "__main__":
    run_agent(WebScraperAgent())
