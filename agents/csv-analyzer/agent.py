import csv
import io
from agentgate_sdk import AgentHandler, run_agent


class CsvAnalyzerAgent(AgentHandler):
    def handle(self, input_data):
        csv_data = input_data["csv_data"]
        delimiter = input_data.get("delimiter", ",")

        reader = csv.reader(io.StringIO(csv_data), delimiter=delimiter)
        rows = list(reader)

        if not rows:
            return {"row_count": 0, "columns": [], "stats": {}}

        columns = rows[0]
        data_rows = rows[1:]
        row_count = len(data_rows)

        # Build column data
        column_values = {col: [] for col in columns}
        for row in data_rows:
            for i, col in enumerate(columns):
                if i < len(row):
                    column_values[col].append(row[i])

        # Calculate stats for numeric columns
        stats = {}
        for col in columns:
            numeric_values = []
            for val in column_values[col]:
                val = val.strip()
                if val == "":
                    continue
                try:
                    numeric_values.append(float(val))
                except ValueError:
                    continue

            if numeric_values:
                stats[col] = {
                    "min": min(numeric_values),
                    "max": max(numeric_values),
                    "mean": round(sum(numeric_values) / len(numeric_values), 4),
                    "count": len(numeric_values),
                    "type": "numeric",
                }
            else:
                non_empty = [v for v in column_values[col] if v.strip()]
                unique_count = len(set(non_empty))
                stats[col] = {
                    "count": len(non_empty),
                    "unique": unique_count,
                    "type": "text",
                }

        return {
            "row_count": row_count,
            "columns": columns,
            "stats": stats,
        }


if __name__ == "__main__":
    run_agent(CsvAnalyzerAgent())
