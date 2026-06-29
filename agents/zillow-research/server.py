"""External agent HTTP wrapper for Zillow Research Agent."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import agent

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)

app = FastAPI()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/")
async def invoke(request: Request):
    body = await request.json()
    input_data = body.get("input", body)

    try:
        result = await agent.handle(input_data)
        return JSONResponse(content={"output": result})
    except Exception as e:
        logger.exception("Agent execution failed")
        return JSONResponse(
            status_code=500,
            content={"output": {"error": str(e)}},
        )
