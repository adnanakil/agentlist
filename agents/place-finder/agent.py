import json
import os
import ssl
from urllib.request import Request, urlopen as _urlopen
from agentgate_sdk import AgentHandler, run_agent

try:
    import certifi
    _ssl_ctx = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _ssl_ctx = ssl.create_default_context()

def urlopen(req, **kw):
    return _urlopen(req, context=_ssl_ctx, **kw)

FIELD_MASK = ",".join([
    "places.displayName",
    "places.formattedAddress",
    "places.rating",
    "places.userRatingCount",
    "places.priceLevel",
    "places.currentOpeningHours",
    "places.types",
    "places.googleMapsUri",
    "places.primaryType",
    "places.websiteUri",
])

PRICE_MAP = {
    "PRICE_LEVEL_FREE": "Free",
    "PRICE_LEVEL_INEXPENSIVE": "$",
    "PRICE_LEVEL_MODERATE": "$$",
    "PRICE_LEVEL_EXPENSIVE": "$$$",
    "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$",
}


class PlaceFinderAgent(AgentHandler):
    def handle(self, input_data):
        api_key = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_PLACES_API_KEY", "")
        if not api_key:
            return {"error": "No Google/Gemini API key configured"}

        query = input_data.get("query", "")
        mode = input_data.get("mode", "text")
        lat = input_data.get("latitude", 40.7454)
        lng = input_data.get("longitude", -74.0002)
        radius = input_data.get("radius", 1000)
        max_results = min(input_data.get("max_results", 10), 20)

        if mode == "nearby":
            data = self._search_nearby(api_key, lat, lng, radius, query, max_results)
        else:
            data = self._text_search(api_key, query, lat, lng, radius, max_results)

        return self._format_places(data)

    def _search_nearby(self, api_key, lat, lng, radius, types_str, max_results):
        url = "https://places.googleapis.com/v1/places:searchNearby"
        types = [t.strip() for t in types_str.split(",")] if types_str else []
        payload = {
            "maxResultCount": max_results,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": float(radius),
                }
            },
        }
        if types:
            payload["includedTypes"] = types

        req = Request(url, json.dumps(payload).encode(), headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        })
        resp = urlopen(req, timeout=15)
        return json.loads(resp.read())

    def _text_search(self, api_key, query, lat, lng, radius, max_results):
        url = "https://places.googleapis.com/v1/places:searchText"
        payload = {
            "textQuery": query,
            "maxResultCount": max_results,
        }
        if lat is not None and lng is not None:
            payload["locationBias"] = {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": float(radius),
                }
            }

        req = Request(url, json.dumps(payload).encode(), headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        })
        resp = urlopen(req, timeout=15)
        return json.loads(resp.read())

    def _format_places(self, data):
        places = data.get("places", [])
        if not places:
            return {"results": [], "count": 0, "message": "No places found."}

        results = []
        for p in places:
            entry = {
                "name": p.get("displayName", {}).get("text", "Unknown"),
                "address": p.get("formattedAddress", ""),
                "rating": p.get("rating"),
                "reviews": p.get("userRatingCount", 0),
                "price": PRICE_MAP.get(p.get("priceLevel", ""), ""),
                "type": (p.get("primaryType") or "").replace("_", " "),
                "maps_url": p.get("googleMapsUri", ""),
                "website": p.get("websiteUri", ""),
            }
            hours = p.get("currentOpeningHours", {})
            if hours:
                entry["open_now"] = hours.get("openNow")
            results.append(entry)

        return {"results": results, "count": len(results)}


if __name__ == "__main__":
    run_agent(PlaceFinderAgent())
