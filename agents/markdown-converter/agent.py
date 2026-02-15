import re
from agentgate_sdk import AgentHandler, run_agent


class MarkdownConverterAgent(AgentHandler):
    def handle(self, input_data):
        markdown = input_data["markdown"]
        html = self._convert(markdown)
        return {"html": html}

    def _convert(self, markdown):
        lines = markdown.split("\n")
        html_lines = []
        in_code_block = False
        code_lang = ""
        code_lines = []
        in_ul = False
        in_ol = False

        i = 0
        while i < len(lines):
            line = lines[i]

            # Code blocks (fenced)
            if line.strip().startswith("```"):
                if not in_code_block:
                    in_code_block = True
                    code_lang = line.strip()[3:].strip()
                    code_lines = []
                else:
                    in_code_block = False
                    code_content = self._escape_html("\n".join(code_lines))
                    if code_lang:
                        html_lines.append(f'<pre><code class="language-{code_lang}">{code_content}</code></pre>')
                    else:
                        html_lines.append(f"<pre><code>{code_content}</code></pre>")
                i += 1
                continue

            if in_code_block:
                code_lines.append(line)
                i += 1
                continue

            # Close lists if current line isn't a list item
            stripped = line.strip()
            is_ul_item = bool(re.match(r'^[\*\-\+]\s+', stripped))
            is_ol_item = bool(re.match(r'^\d+\.\s+', stripped))

            if in_ul and not is_ul_item:
                html_lines.append("</ul>")
                in_ul = False
            if in_ol and not is_ol_item:
                html_lines.append("</ol>")
                in_ol = False

            # Blank lines
            if not stripped:
                html_lines.append("")
                i += 1
                continue

            # Headers
            header_match = re.match(r'^(#{1,6})\s+(.*)', line)
            if header_match:
                level = len(header_match.group(1))
                text = self._inline(header_match.group(2))
                html_lines.append(f"<h{level}>{text}</h{level}>")
                i += 1
                continue

            # Horizontal rules
            if re.match(r'^(\*{3,}|-{3,}|_{3,})\s*$', stripped):
                html_lines.append("<hr>")
                i += 1
                continue

            # Unordered list items
            if is_ul_item:
                if not in_ul:
                    html_lines.append("<ul>")
                    in_ul = True
                item_text = re.sub(r'^[\*\-\+]\s+', '', stripped)
                html_lines.append(f"<li>{self._inline(item_text)}</li>")
                i += 1
                continue

            # Ordered list items
            if is_ol_item:
                if not in_ol:
                    html_lines.append("<ol>")
                    in_ol = True
                item_text = re.sub(r'^\d+\.\s+', '', stripped)
                html_lines.append(f"<li>{self._inline(item_text)}</li>")
                i += 1
                continue

            # Blockquote
            if stripped.startswith(">"):
                quote_text = re.sub(r'^>\s?', '', stripped)
                html_lines.append(f"<blockquote>{self._inline(quote_text)}</blockquote>")
                i += 1
                continue

            # Regular paragraph
            html_lines.append(f"<p>{self._inline(stripped)}</p>")
            i += 1

        # Close any open lists
        if in_ul:
            html_lines.append("</ul>")
        if in_ol:
            html_lines.append("</ol>")

        return "\n".join(html_lines)

    def _inline(self, text):
        """Process inline markdown elements."""
        # Inline code (must be before bold/italic to avoid conflicts)
        text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
        # Images
        text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', r'<img src="\2" alt="\1">', text)
        # Links
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
        # Bold (**text** or __text__)
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'__(.+?)__', r'<strong>\1</strong>', text)
        # Italic (*text* or _text_)
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        text = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'<em>\1</em>', text)
        return text

    def _escape_html(self, text):
        """Escape HTML special characters."""
        text = text.replace("&", "&amp;")
        text = text.replace("<", "&lt;")
        text = text.replace(">", "&gt;")
        text = text.replace('"', "&quot;")
        return text


if __name__ == "__main__":
    run_agent(MarkdownConverterAgent())
