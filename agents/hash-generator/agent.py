import hashlib
from agentgate_sdk import AgentHandler, run_agent


class HashGeneratorAgent(AgentHandler):
    def handle(self, input_data):
        text = input_data["text"]
        algorithm = input_data["algorithm"]

        algorithms = {
            "md5": hashlib.md5,
            "sha1": hashlib.sha1,
            "sha256": hashlib.sha256,
        }

        if algorithm not in algorithms:
            raise ValueError(f"Unsupported algorithm: {algorithm}. Use one of: {list(algorithms.keys())}")

        hash_func = algorithms[algorithm]
        hash_value = hash_func(text.encode("utf-8")).hexdigest()

        return {
            "hash": hash_value,
            "algorithm": algorithm,
        }


if __name__ == "__main__":
    run_agent(HashGeneratorAgent())
