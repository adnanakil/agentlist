FROM python:3.12-slim

WORKDIR /app

COPY agents/zillow-research/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agents/zillow-research/agent.py agents/zillow-research/server.py ./

EXPOSE 9000

CMD uvicorn server:app --host 0.0.0.0 --port $PORT
