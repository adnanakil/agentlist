import base64
import json
import os
import ssl
import subprocess
import tempfile
from agentgate_sdk import AgentHandler, run_agent

try:
    import certifi
    _ssl_ctx = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _ssl_ctx = ssl.create_default_context()

from urllib.request import Request, urlopen as _urlopen


def urlopen(req, **kw):
    return _urlopen(req, context=_ssl_ctx, **kw)


def upload_image(filepath):
    """Upload image to 0x0.st and return the URL."""
    try:
        r = subprocess.run(
            ["curl", "-s", "-F", f"file=@{filepath}", "https://0x0.st"],
            capture_output=True, text=True, timeout=30,
        )
        url = r.stdout.strip()
        if url.startswith("http"):
            return url
    except Exception:
        pass
    return None


class ImageGeneratorAgent(AgentHandler):
    def handle(self, input_data):
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            return {"error": "No GEMINI_API_KEY configured"}

        prompt = input_data.get("prompt", "a beautiful landscape")

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.5-flash-image:generateContent?key={api_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": f"Generate an image: {prompt}"}]}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
        }
        req = Request(
            url, json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )

        try:
            resp = urlopen(req, timeout=60)
            data = json.loads(resp.read())
        except Exception as e:
            return {"error": f"Gemini API call failed: {e}"}

        candidates = data.get("candidates", [])
        if not candidates:
            return {"error": "No candidates in response"}

        parts = candidates[0].get("content", {}).get("parts", [])
        text_response = ""

        for part in parts:
            if "inlineData" in part:
                img_data = base64.b64decode(part["inlineData"]["data"])
                mime = part["inlineData"].get("mimeType", "image/png")
                ext = "png" if "png" in mime else "jpg"

                with tempfile.NamedTemporaryFile(
                    suffix=f".{ext}", delete=False
                ) as f:
                    f.write(img_data)
                    filepath = f.name

                image_url = upload_image(filepath)

                # Clean up temp file
                try:
                    os.unlink(filepath)
                except OSError:
                    pass

                return {
                    "success": True,
                    "url": image_url or "",
                    "description": text_response or prompt,
                    "prompt": prompt,
                }
            elif "text" in part:
                text_response = part["text"]

        return {
            "error": "No image in response",
            "text": text_response[:500] if text_response else "",
        }


if __name__ == "__main__":
    run_agent(ImageGeneratorAgent())
