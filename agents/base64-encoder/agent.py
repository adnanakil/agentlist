import base64
from agentgate_sdk import AgentHandler, run_agent


class Base64EncoderAgent(AgentHandler):
    def handle(self, input_data):
        text = input_data["text"]
        operation = input_data["operation"]

        if operation == "encode":
            result = base64.b64encode(text.encode("utf-8")).decode("ascii")
        elif operation == "decode":
            try:
                result = base64.b64decode(text).decode("utf-8")
            except Exception as e:
                raise ValueError(f"Invalid Base64 input: {e}")
        else:
            raise ValueError(f"Unsupported operation: {operation}. Use 'encode' or 'decode'.")

        return {"result": result}


if __name__ == "__main__":
    run_agent(Base64EncoderAgent())
