import json
import re
import textwrap
from agentgate_sdk import AgentHandler, run_agent


class CodeFormatterAgent(AgentHandler):
    def handle(self, input_data):
        code = input_data["code"]
        language = input_data["language"]

        if language == "json":
            formatted = self._format_json(code)
        elif language == "python":
            formatted = self._format_python(code)
        else:
            raise ValueError(f"Unsupported language: {language}")

        return {"formatted": formatted}

    def _format_json(self, code):
        """Parse and re-serialize JSON with consistent indentation."""
        try:
            parsed = json.loads(code)
            return json.dumps(parsed, indent=2, sort_keys=False)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")

    def _format_python(self, code):
        """Apply basic Python formatting rules."""
        lines = code.splitlines()
        formatted_lines = []
        indent_level = 0
        indent_str = "    "
        block_openers = {"def", "class", "if", "elif", "else", "for", "while",
                         "try", "except", "finally", "with", "async"}

        # First, dedent the entire block to normalize
        code = textwrap.dedent(code)
        lines = code.splitlines()

        formatted_lines = []
        indent_level = 0
        prev_was_blank = False
        prev_was_class_or_def = False

        for i, raw_line in enumerate(lines):
            stripped = raw_line.strip()

            # Skip multiple consecutive blank lines
            if not stripped:
                if not prev_was_blank:
                    formatted_lines.append("")
                prev_was_blank = True
                prev_was_class_or_def = False
                continue
            prev_was_blank = False

            # Decrease indent for dedenting keywords
            if stripped.startswith(("elif ", "elif:", "else:", "except:", "except ",
                                    "finally:", "except(")):
                indent_level = max(0, indent_level - 1)

            # Add blank line before class/def at top level
            if (stripped.startswith("def ") or stripped.startswith("class ") or
                    stripped.startswith("async def ")):
                if formatted_lines and formatted_lines[-1] != "":
                    formatted_lines.append("")
                prev_was_class_or_def = True

            # Build the formatted line
            formatted_line = indent_str * indent_level + stripped
            formatted_lines.append(formatted_line)

            # Increase indent if line ends with colon (block opener)
            if stripped.endswith(":") and not stripped.startswith("#"):
                first_word = stripped.split()[0].rstrip(":")
                if first_word in block_openers or stripped.startswith("@"):
                    if not stripped.startswith("@"):
                        indent_level += 1

            # Handle return/break/continue/pass/raise - next non-blank, non-dedent
            # line should be at lower indent (handled naturally by block structure)

        # Remove trailing blank lines
        while formatted_lines and formatted_lines[-1] == "":
            formatted_lines.pop()

        # Ensure trailing newline
        result = "\n".join(formatted_lines)
        if result and not result.endswith("\n"):
            result += "\n"

        return result


if __name__ == "__main__":
    run_agent(CodeFormatterAgent())
