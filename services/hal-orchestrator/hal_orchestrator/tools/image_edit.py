"""image_edit tool — edit/transform images using Gemini image model."""

from __future__ import annotations

import base64
import structlog

from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()

GEMINI_IMAGE_API = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


async def tool_image_edit(args: dict, ctx: ToolContext) -> str:
    """Edit or transform an image using Gemini image model."""
    prompt = args.get("prompt", "")
    if not prompt:
        return "Error: prompt is required"

    if not ctx.images:
        return "Error: no image was sent with this message. Ask the user to send a photo."

    image = ctx.images[0]

    # Call Gemini image model
    url = GEMINI_IMAGE_API.format(model=ctx.settings.gemini_image_model)
    url += f"?key={ctx.settings.gemini_api_key}"

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": image["mime_type"],
                            "data": image["data"],
                        }
                    },
                ]
            }
        ],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }

    try:
        resp = await ctx.http_client.post(url, json=payload, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.exception("image_edit.gemini_error")
        return f"Image editing failed: {exc}"

    # Extract edited image from response
    candidates = data.get("candidates", [])
    if not candidates:
        return "Image editing failed: no response from model"

    parts = candidates[0].get("content", {}).get("parts", [])

    image_data = None
    description = ""
    for part in parts:
        if "inlineData" in part:
            image_data = part["inlineData"]
        elif "text" in part:
            description = part["text"]

    if not image_data:
        return description or "Image editing failed: model did not return an image"

    # Store base64 image for bridge to send as file attachment (keep only the latest)
    mime = image_data.get("mimeType", "image/png")
    ext = "png" if "png" in mime else "jpg"
    ctx.result_images.clear()
    ctx.result_images.append({
        "mime_type": mime,
        "data": image_data["data"],
        "ext": ext,
    })

    log.info("image_edit.success", mime=mime, size_kb=len(image_data["data"]) // 1370)
    return description or "Image edited successfully. The image will be sent as an attachment."
