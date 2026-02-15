import re
from agentgate_sdk import AgentHandler, run_agent


class RegexTesterAgent(AgentHandler):
    def handle(self, input_data):
        pattern = input_data["pattern"]
        text = input_data["text"]
        flags_str = input_data.get("flags", "")

        # Parse flags
        flags = 0
        flag_map = {
            "i": re.IGNORECASE,
            "m": re.MULTILINE,
            "s": re.DOTALL,
        }
        for char in flags_str:
            if char in flag_map:
                flags |= flag_map[char]
            elif char.strip():
                raise ValueError(f"Unknown flag: '{char}'. Supported flags: i (ignorecase), m (multiline), s (dotall)")

        try:
            compiled = re.compile(pattern, flags)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}")

        matches = []
        for match in compiled.finditer(text):
            match_info = {
                "match": match.group(),
                "start": match.start(),
                "end": match.end(),
            }
            # Include named groups if any
            if match.groupdict():
                match_info["groups"] = {k: v for k, v in match.groupdict().items() if v is not None}
            # Include positional groups if any
            if match.groups():
                match_info["captures"] = list(match.groups())

            matches.append(match_info)

        return {
            "matches": matches,
            "match_count": len(matches),
        }


if __name__ == "__main__":
    run_agent(RegexTesterAgent())
