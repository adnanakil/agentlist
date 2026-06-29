"""Zillow Research Agent — uses Bright Data dataset scraper + Claude AI analysis."""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
from dataclasses import dataclass, field, asdict
from urllib.parse import quote_plus
from urllib.request import Request, urlopen as _urlopen

import anthropic
import httpx

try:
    import certifi
    _ssl_ctx = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _ssl_ctx = ssl.create_default_context()

logger = logging.getLogger(__name__)

BRIGHTDATA_API = "https://api.brightdata.com/datasets/v3"
DATASET_ID = "gd_lfqkr8wm13ixtbd8f5"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Comp:
    address: str = ""
    sold_price: int | None = None
    sold_date: str = ""
    sqft: int | None = None
    beds: int | None = None
    baths: float | None = None


@dataclass
class ListingDetail:
    address: str = ""
    price: int | None = None
    beds: int | None = None
    baths: float | None = None
    sqft: int | None = None
    url: str = ""
    year_built: int | None = None
    days_on_market: int | None = None
    lot_size: str = ""
    hoa: str | None = None
    description: str = ""
    zestimate: int | None = None
    tax_history: list[dict] = field(default_factory=list)
    price_history: list[dict] = field(default_factory=list)
    comps: list[Comp] = field(default_factory=list)
    analysis: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Bright Data Zillow scraper
# ---------------------------------------------------------------------------

def _brightdata_api_key() -> str:
    return os.environ.get("BRIGHTDATA_API_KEY", "")


def _is_shell_record(record: dict) -> bool:
    """Bright Data returns {"timestamp","input"} shells when the URL yields no data."""
    return not record.get("zpid") and not record.get("price") and not record.get("streetAddress")


def _normalize_brightdata_items(data) -> list[dict]:
    """Coerce Bright Data response into a list of property dicts, dropping shells."""
    items: list[dict] = []
    if isinstance(data, list):
        raw_items = data
    elif isinstance(data, dict):
        raw_items = [data]
    else:
        return []
    for item in raw_items:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except json.JSONDecodeError:
                continue
        if not isinstance(item, dict) or _is_shell_record(item):
            continue
        items.append(item)
    return items


async def _brightdata_scrape(payload: list[dict]) -> list[dict]:
    """Synchronous Bright Data detail scrape. Returns real property records only."""
    api_key = _brightdata_api_key()
    if not api_key:
        raise RuntimeError("BRIGHTDATA_API_KEY not configured")

    url = f"{BRIGHTDATA_API}/scrape?dataset_id={DATASET_ID}&format=json"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    results = _normalize_brightdata_items(data)
    logger.info("Bright Data sync scrape: %d real records (from %d inputs)", len(results), len(payload))
    return results


async def _brightdata_discover_trigger(filters: dict) -> str:
    """Kick off an async discover_new job. Returns a snapshot_id for polling."""
    api_key = _brightdata_api_key()
    if not api_key:
        raise RuntimeError("BRIGHTDATA_API_KEY not configured")

    url = (
        f"{BRIGHTDATA_API}/trigger?dataset_id={DATASET_ID}"
        f"&type=discover_new&discover_by=input_filters"
    )
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=[filters], headers=headers)
        resp.raise_for_status()
        data = resp.json()
    snapshot_id = data.get("snapshot_id")
    if not snapshot_id:
        raise RuntimeError(f"Bright Data trigger returned no snapshot_id: {data}")
    logger.info("Bright Data discover triggered: %s", snapshot_id)
    return snapshot_id


async def _brightdata_snapshot_status(snapshot_id: str) -> dict:
    """Return progress metadata: {status: running|ready|failed, ...}."""
    api_key = _brightdata_api_key()
    url = f"{BRIGHTDATA_API}/progress/{snapshot_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


def _record_matches(item: dict, min_price, max_price, min_beds) -> bool:
    price = item.get("price")
    beds = item.get("bedrooms") or item.get("beds")
    if min_price and price and price < min_price:
        return False
    if max_price and price and price > max_price:
        return False
    if min_beds and beds and beds < min_beds:
        return False
    return True


async def _brightdata_snapshot_download(
    snapshot_id: str,
    max_records: int = 30,
    min_price: int | None = None,
    max_price: int | None = None,
    min_beds: int | None = None,
    max_scanned: int = 2000,
) -> list[dict]:
    """Stream JSONL from a completed discover snapshot, stream-filter, stop after max_records.

    Bright Data snapshots can be hundreds of MB with thousands of records, and Bright Data's
    discover API can't filter by price/beds server-side. We stream line-by-line, apply filters
    inline, and stop once we have max_records matching items or have scanned max_scanned lines.
    """
    api_key = _brightdata_api_key()
    url = f"{BRIGHTDATA_API}/snapshot/{snapshot_id}?format=jsonl"
    headers = {"Authorization": f"Bearer {api_key}"}
    results: list[dict] = []
    scanned = 0
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("GET", url, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                scanned += 1
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(item, dict) or _is_shell_record(item):
                    continue
                if not _record_matches(item, min_price, max_price, min_beds):
                    continue
                results.append(item)
                if len(results) >= max_records:
                    break
                if scanned >= max_scanned:
                    break
    logger.info(
        "Bright Data snapshot %s: scanned=%d matched=%d", snapshot_id, scanned, len(results)
    )
    return results


def _resolve_via_autocomplete(location: str) -> list[dict]:
    """Use Zillow's autocomplete API to resolve an address to listing URLs."""
    url = f"https://www.zillowstatic.com/autocomplete/v3/suggestions?q={quote_plus(location)}"
    try:
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        })
        data = json.loads(_urlopen(req, context=_ssl_ctx, timeout=15).read())
        results = []
        for item in data.get("results", []):
            display = item.get("display", "")
            meta = item.get("metaData", {})
            zpid = meta.get("zpid")
            if zpid:
                slug = display.replace(" ", "-").replace(",", "").replace(".", "").replace("#", "%23")
                listing_url = f"https://www.zillow.com/homedetails/{slug}/{zpid}_zpid/"
                results.append({"address": display, "url": listing_url, "zpid": zpid, "type": "address"})
            elif meta.get("city") or meta.get("state"):
                results.append({"address": display, "type": "region"})
        return results
    except Exception as e:
        logger.warning("Autocomplete API failed: %s", e)
        return []


def _raw_to_listing(raw: dict) -> ListingDetail:
    """Convert a Bright Data raw property record to ListingDetail."""
    # Address
    addr_parts = []
    for f in ("streetAddress", "street_address"):
        if raw.get(f):
            addr_parts.append(raw[f])
            break
    for f in ("city",):
        if raw.get(f):
            addr_parts.append(raw[f])
    for f in ("state",):
        if raw.get(f):
            addr_parts.append(raw[f])
    for f in ("zipcode", "zip_code"):
        if raw.get(f):
            addr_parts.append(raw[f])
    address = ", ".join(addr_parts) if addr_parts else raw.get("address", "")

    # HOA
    hoa_val = raw.get("monthlyHoaFee") or raw.get("hoa")
    hoa_str = None
    if hoa_val and isinstance(hoa_val, (int, float)) and hoa_val > 0:
        hoa_str = f"${int(hoa_val)}/mo"
    elif isinstance(hoa_val, str) and hoa_val:
        hoa_str = hoa_val

    # Lot size
    lot = raw.get("lotSize") or raw.get("lot_size") or raw.get("lotAreaValue")
    lot_str = ""
    if lot:
        if isinstance(lot, (int, float)):
            lot_str = f"{lot:,.0f} sqft"
        else:
            lot_str = str(lot)

    detail = ListingDetail(
        address=address,
        price=raw.get("price"),
        beds=raw.get("bedrooms") or raw.get("beds"),
        baths=raw.get("bathrooms") or raw.get("baths"),
        sqft=raw.get("livingArea") or raw.get("living_area") or raw.get("sqft"),
        url=raw.get("url", ""),
        year_built=raw.get("yearBuilt") or raw.get("year_built"),
        days_on_market=raw.get("daysOnZillow") or raw.get("days_on_zillow") or raw.get("days_on_market"),
        lot_size=lot_str,
        hoa=hoa_str,
        description=(raw.get("description") or "")[:500],
        zestimate=raw.get("zestimate"),
    )

    # Price history
    for ph in (raw.get("priceHistory") or raw.get("price_history") or [])[:10]:
        detail.price_history.append({
            "date": ph.get("date", ""),
            "event": ph.get("event", ""),
            "value": f"${ph['price']:,}" if ph.get("price") else "",
        })

    # Tax history
    for th in (raw.get("taxHistory") or raw.get("tax_history") or [])[:5]:
        detail.tax_history.append({
            "year": th.get("year", ""),
            "value": f"${th['value']:,}" if th.get("value") else "",
            "tax": f"${th['taxPaid']:,}" if th.get("taxPaid") else "",
        })

    # Nearby comps (items may be JSON strings or dicts)
    for nh_raw in (raw.get("nearbyHomes") or raw.get("nearby_homes") or [])[:6]:
        if isinstance(nh_raw, str):
            try:
                nh = json.loads(nh_raw)
            except json.JSONDecodeError:
                continue
        elif isinstance(nh_raw, dict):
            nh = nh_raw
        else:
            continue
        addr = nh.get("address", {})
        addr_str = addr.get("streetAddress", "") if isinstance(addr, dict) else str(addr)
        detail.comps.append(Comp(
            address=addr_str,
            sold_price=nh.get("price"),
            sqft=nh.get("livingArea"),
            beds=nh.get("bedrooms"),
            baths=nh.get("bathrooms"),
        ))

    return detail


# ---------------------------------------------------------------------------
# AI Analysis
# ---------------------------------------------------------------------------

def analyze_property(listing: ListingDetail, comps: list[Comp]) -> dict:
    """Use Claude to synthesize a valuation analysis from listing data + comps."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {
            "comp_summary": "Analysis unavailable — no ANTHROPIC_API_KEY configured.",
            "risks": [],
            "estimated_value_range": [],
            "verdict": "N/A",
        }

    client = anthropic.Anthropic(api_key=api_key)

    comps_text = ""
    for i, c in enumerate(comps, 1):
        if c.sold_price:
            comps_text += (
                f"  {i}. {c.address} — ${c.sold_price:,}"
                f"{f' on {c.sold_date}' if c.sold_date else ''}, "
                f"{c.beds}bd/{c.baths}ba, {c.sqft} sqft\n"
            )
        else:
            comps_text += f"  {i}. {c.address} — details incomplete\n"

    price_str = f"${listing.price:,}" if listing.price else "Unknown"
    zest_str = f"${listing.zestimate:,}" if listing.zestimate else "Not available"

    prompt = f"""Analyze this real estate listing and comparable sales. Provide a concise investment analysis.

LISTING:
- Address: {listing.address or 'Unknown'}
- Price: {price_str}
- Zestimate: {zest_str}
- Beds/Baths/SqFt: {listing.beds or '?'}bd / {listing.baths or '?'}ba / {listing.sqft or '?'} sqft
- Year Built: {listing.year_built or 'Unknown'}
- Days on Market: {listing.days_on_market or 'Unknown'}
- Lot Size: {listing.lot_size or 'Unknown'}
- HOA: {listing.hoa or 'None'}
- Description: {(listing.description or '')[:300]}
- Price History: {json.dumps(listing.price_history[:5]) if listing.price_history else 'None available'}
- Tax History: {json.dumps(listing.tax_history[:3]) if listing.tax_history else 'None available'}

COMPARABLE SALES (nearby recently sold):
{comps_text if comps_text else '  No comps available from listing page.'}

Respond in this exact JSON format (no markdown, no code fences):
{{
  "comp_summary": "1-2 sentence comparison to comps, including price per sqft analysis",
  "risks": ["risk 1", "risk 2", "risk 3"],
  "estimated_value_range": [low_int, high_int],
  "verdict": "One sentence: overpriced / fair / underpriced with reasoning"
}}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return json.loads(text)
    except Exception as e:
        logger.error("Claude analysis failed: %s", e)
        return {
            "comp_summary": f"Analysis error: {e}",
            "risks": [],
            "estimated_value_range": [],
            "verdict": "Unable to analyze",
        }


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

def _analyze_and_filter(
    raw_results: list[dict],
    min_price: int | None,
    max_price: int | None,
    min_beds: int | None,
    limit: int = 5,
) -> list[dict]:
    """Map raw records → ListingDetail, apply filters, run Claude analysis."""
    listings_out: list[dict] = []
    for raw in raw_results:
        detail = _raw_to_listing(raw)
        if min_price and detail.price and detail.price < min_price:
            continue
        if max_price and detail.price and detail.price > max_price:
            continue
        if min_beds and detail.beds and detail.beds < min_beds:
            continue
        detail.analysis = analyze_property(detail, detail.comps)
        listings_out.append(_serialize_listing(detail))
        if len(listings_out) >= limit:
            break
    return listings_out


async def handle(input_data: dict) -> dict:
    """Orchestrate search → details → analysis via Bright Data + Claude."""

    listing_url = input_data.get("listing_url")
    location = input_data.get("location", "")
    snapshot_id = input_data.get("snapshot_id")
    min_price = input_data.get("min_price")
    max_price = input_data.get("max_price")
    min_beds = input_data.get("min_beds")
    home_type = input_data.get("home_type")  # e.g. "Houses", "Apartments", "Condos", "Townhomes"

    # Mode 1: Resume an async discover snapshot
    if snapshot_id:
        progress = await _brightdata_snapshot_status(snapshot_id)
        status = progress.get("status", "unknown")
        if status != "ready":
            return {
                "status": status,
                "snapshot_id": snapshot_id,
                "search_location": location,
                "message": (
                    f"Discover job {status}. Retry this invocation with the same "
                    f"snapshot_id in 60-120s to fetch results."
                ),
            }
        raw_results = await _brightdata_snapshot_download(
            snapshot_id,
            min_price=min_price,
            max_price=max_price,
            min_beds=min_beds,
        )
        listings_out = _analyze_and_filter(raw_results, min_price, max_price, min_beds)
        return {
            "status": "ready",
            "snapshot_id": snapshot_id,
            "search_location": location or "discover",
            "listings_analyzed": len(listings_out),
            "listings": listings_out,
        }

    # Mode 2: Direct analysis of a single listing URL
    if listing_url:
        logger.info("Fetching single listing: %s", listing_url)
        raw_results = await _brightdata_scrape([{"url": listing_url}])
        if not raw_results:
            return {"error": f"Could not fetch data for {listing_url}"}
        detail = _raw_to_listing(raw_results[0])
        detail.url = listing_url
        detail.analysis = analyze_property(detail, detail.comps)
        return {
            "search_location": detail.address or listing_url,
            "listings_analyzed": 1,
            "listings": [_serialize_listing(detail)],
        }

    # Mode 3: Location search
    if not location:
        return {"error": "Provide 'location', 'listing_url', or 'snapshot_id'."}

    # 3a. Autocomplete-resolved addresses (works for ZIP codes, street queries)
    ac_results = _resolve_via_autocomplete(location)
    address_hits = [r for r in ac_results if r.get("type") == "address"]
    if address_hits:
        urls = [r["url"] for r in address_hits[:5]]
        logger.info("Autocomplete resolved %d addresses, fetching via Bright Data", len(urls))
        raw_results = await _brightdata_scrape([{"url": u} for u in urls])
        if raw_results:
            listings_out = _analyze_and_filter(raw_results, min_price, max_price, min_beds)
            return {
                "search_location": location,
                "listings_analyzed": len(listings_out),
                "listings": listings_out,
            }

    # 3b. Broad location — kick off async discover and return snapshot_id to resume
    logger.info("No autocomplete address hits; triggering Bright Data discover for '%s'", location)
    # Bright Data discover only accepts location, HomeType, listingCategory.
    # Price/beds filters are applied client-side while streaming the snapshot.
    filters: dict = {
        "location": location,
        "listingCategory": "House for sale",
        "HomeType": home_type or "Houses",
    }

    try:
        snap_id = await _brightdata_discover_trigger(filters)
    except Exception as e:
        logger.exception("Discover trigger failed")
        return {
            "search_location": location,
            "listings_analyzed": 0,
            "listings": [],
            "error": f"Could not start Zillow search: {e}",
        }

    return {
        "status": "queued",
        "snapshot_id": snap_id,
        "search_location": location,
        "message": (
            "Zillow search queued via Bright Data discover. Retry this agent with "
            f'`{{"snapshot_id": "{snap_id}"}}` in 60-180 seconds to fetch results. '
            "For faster results, pass a specific address, ZIP code, or listing_url."
        ),
    }


def _serialize_listing(detail: ListingDetail) -> dict:
    """Convert a ListingDetail to the output JSON shape."""
    return {
        "address": detail.address,
        "price": detail.price,
        "beds": detail.beds,
        "baths": detail.baths,
        "sqft": detail.sqft,
        "url": detail.url,
        "year_built": detail.year_built,
        "days_on_market": detail.days_on_market,
        "lot_size": detail.lot_size,
        "hoa": detail.hoa,
        "zestimate": detail.zestimate,
        "comps": [asdict(c) for c in detail.comps],
        "analysis": detail.analysis,
    }
