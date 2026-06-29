FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY agent-sdk/python /sdk
RUN pip install --no-cache-dir /sdk pyyaml certifi

COPY agents/image-generator/ /app/

CMD ["python", "agent.py"]
