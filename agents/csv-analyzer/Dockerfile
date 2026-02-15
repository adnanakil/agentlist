FROM python:3.12-slim

WORKDIR /app

COPY agent-sdk/python /sdk
RUN pip install --no-cache-dir /sdk pyyaml

COPY agents/csv-analyzer/ /app/

CMD ["python", "agent.py"]
