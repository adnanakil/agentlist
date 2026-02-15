from agentgate_sdk import AgentHandler, run_agent


class EchoAgent(AgentHandler):
    def handle(self, input_data):
        return {
            "echoed_message": input_data.get("message", ""),
            "input_keys": list(input_data.keys()),
        }


if __name__ == "__main__":
    run_agent(EchoAgent())
