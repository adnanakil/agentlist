from agentgate_sdk import AgentHandler, run_agent


class JsonTransformerAgent(AgentHandler):
    def handle(self, input_data):
        data = input_data["data"]
        operations = input_data.get("operations", [])

        result = data
        for op in operations:
            op_type = op.get("type")
            args = op.get("args", {})
            result = self._apply(result, op_type, args)

        return {"result": result}

    def _apply(self, data, op_type, args):
        if op_type == "pick":
            keys = args.get("keys", [])
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if k in keys}
            if isinstance(data, list):
                return [{k: v for k, v in item.items() if k in keys} for item in data if isinstance(item, dict)]

        elif op_type == "omit":
            keys = args.get("keys", [])
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if k not in keys}
            if isinstance(data, list):
                return [{k: v for k, v in item.items() if k not in keys} for item in data if isinstance(item, dict)]

        elif op_type == "rename":
            mapping = args.get("mapping", {})
            if isinstance(data, dict):
                return {mapping.get(k, k): v for k, v in data.items()}
            if isinstance(data, list):
                return [{mapping.get(k, k): v for k, v in item.items()} for item in data if isinstance(item, dict)]

        elif op_type == "flatten":
            if isinstance(data, dict):
                return self._flatten_dict(data)

        elif op_type == "filter_keys":
            pattern = args.get("contains", "")
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if pattern in k}

        return data

    def _flatten_dict(self, d, parent_key="", sep="."):
        items = {}
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.update(self._flatten_dict(v, new_key, sep))
            else:
                items[new_key] = v
        return items


if __name__ == "__main__":
    run_agent(JsonTransformerAgent())
