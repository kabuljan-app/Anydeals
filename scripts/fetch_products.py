#!/usr/bin/env python3
"""
Daily product updater for an Amazon Associates site.

What it does each run:
  1. Gets an OAuth token for the Amazon Creators API.
  2. Searches each category's keywords (and looks up any ASINs you listed).
  3. Re-checks every product already on the site so prices are fresh.
  4. Drops products that are no longer available.
  5. Writes site/data/products.json, which the website reads.

Needs only the Python standard library. Credentials come from environment
variables (set as GitHub Secrets):
  AMAZON_CREDENTIAL_ID, AMAZON_CREDENTIAL_SECRET,
  AMAZON_CREDENTIAL_VERSION (e.g. 3.1), AMAZON_PARTNER_TAG (e.g. yourtag-20)
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
DATA_PATH = ROOT / "site" / "data" / "products.json"

API_BASE = "https://creatorsapi.amazon/catalog/v1"
TOKEN_ENDPOINTS = {
    "3.1": "https://api.amazon.com/auth/o2/token",    # US, CA, MX, BR
    "3.2": "https://api.amazon.co.uk/auth/o2/token",  # UK, EU, IN, AE, SA, TR, EG
    "3.3": "https://api.amazon.co.jp/auth/o2/token",  # JP, SG, AU
}
RESOURCES = [
    "images.primary.large",
    "images.primary.medium",
    "itemInfo.title",
    "offersV2.listings.price",
    "offersV2.listings.availability",
    "offersV2.listings.dealDetails",
    "offersV2.listings.condition",
    "offersV2.listings.isBuyBoxWinner",
]
SECONDS_BETWEEN_CALLS = 1.2  # stay under the default 1 request/second limit


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- API client
class CreatorsApi:
    def __init__(self, cred_id, cred_secret, version, partner_tag, marketplace):
        self.cred_id = cred_id
        self.cred_secret = cred_secret
        self.version = version
        self.partner_tag = partner_tag
        self.marketplace = marketplace
        self.token = None
        self.token_expires = 0
        self.last_call = 0.0

    def _get_token(self):
        if self.token and time.time() < self.token_expires - 120:
            return self.token
        endpoint = TOKEN_ENDPOINTS.get(self.version)
        if not endpoint:
            sys.exit(
                f"Credential version '{self.version}' is not supported by this script. "
                "Create a new credential in Associates Central (Tools > Creators API); "
                "new credentials use version 3.1, 3.2 or 3.3."
            )
        body = json.dumps({
            "grant_type": "client_credentials",
            "client_id": self.cred_id,
            "client_secret": self.cred_secret,
            "scope": "creatorsapi::default",
        }).encode()
        req = urllib.request.Request(
            endpoint, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        data = self._send(req, "token")
        self.token = data["access_token"]
        self.token_expires = time.time() + int(data.get("expires_in", 3600))
        return self.token

    def _send(self, req, label, retries=4):
        for attempt in range(retries):
            wait = SECONDS_BETWEEN_CALLS - (time.time() - self.last_call)
            if wait > 0:
                time.sleep(wait)
            self.last_call = time.time()
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:400]
                if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                    backoff = 2 ** attempt * 2
                    log(f"{label}: HTTP {e.code}, retrying in {backoff}s")
                    time.sleep(backoff)
                    continue
                raise RuntimeError(f"{label} failed: HTTP {e.code} {detail}") from None
            except urllib.error.URLError as e:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt * 2)
                    continue
                raise RuntimeError(f"{label} failed: {e.reason}") from None
        raise RuntimeError(f"{label} failed after {retries} attempts")

    def _call(self, operation, payload):
        payload = {
            **payload,
            "partnerTag": self.partner_tag,
            "marketplace": self.marketplace,
            "resources": RESOURCES,
        }
        req = urllib.request.Request(
            f"{API_BASE}/{operation}",
            data=json.dumps(payload).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._get_token()}",
                "Content-Type": "application/json",
                "x-marketplace": self.marketplace,
            },
        )
        return self._send(req, operation)

    def search_items(self, keywords, search_index, count=10, page=1):
        payload = {"keywords": keywords, "itemCount": count, "itemPage": page}
        if search_index:
            payload["searchIndex"] = search_index
        data = self._call("searchItems", payload)
        return extract_items(data)

    def get_items(self, asins):
        items = []
        for i in range(0, len(asins), 10):  # API accepts up to 10 per call
            batch = asins[i:i + 10]
            data = self._call("getItems", {"itemIds": batch, "itemIdType": "ASIN"})
            items.extend(extract_items(data))
        return items


def extract_items(data):
    for key in ("searchResult", "itemsResult", "searchItemsResult"):
        block = data.get(key) or {}
        if block.get("items"):
            return block["items"]
    return []


# ------------------------------------------------------------ data shaping
def dig(obj, *path):
    for p in path:
        if obj is None:
            return None
        obj = obj[p] if isinstance(p, int) and isinstance(obj, list) and len(obj) > p \
            else (obj.get(p) if isinstance(obj, dict) else None)
    return obj


def pick_listing(item):
    listings = dig(item, "offersV2", "listings") or []
    for l in listings:
        if l.get("isBuyBoxWinner"):
            return l
    return listings[0] if listings else None


def to_product(item, category):
    """Turn a raw API item into the small record the website uses.
    Returns None when the item has no buyable offer."""
    listing = pick_listing(item)
    if not listing:
        return None
    avail = listing.get("availability") or {}
    avail_type = avail.get("type") or "UNKNOWN"
    if avail_type in ("OUT_OF_STOCK", "UNAVAILABLE"):
        return None

    price = listing.get("price") or {}
    money = price.get("money") or {}
    basis = dig(price, "savingBasis", "money") or {}
    savings = price.get("savings") or {}
    deal = listing.get("dealDetails")

    image = (dig(item, "images", "primary", "large", "url")
             or dig(item, "images", "primary", "medium", "url") or "")
    title = dig(item, "itemInfo", "title", "displayValue") or "Untitled product"

    return {
        "asin": item["asin"],
        "title": title,
        "url": item.get("detailPageURL"),
        "image": image,
        "category": category,
        "price": money.get("amount"),
        "priceDisplay": money.get("displayAmount"),
        "currency": money.get("currency"),
        "wasDisplay": basis.get("displayAmount"),
        "wasLabel": dig(price, "savingBasis", "savingBasisTypeLabel"),
        "savingsPct": savings.get("percentage") or 0,
        "savingsDisplay": dig(savings, "money", "displayAmount"),
        "availabilityType": avail_type,
        "availabilityMessage": avail.get("message"),
        "maxOrderQty": avail.get("maxOrderQuantity"),
        "dealBadge": deal.get("badge") if deal else None,
        "dealEndTime": deal.get("endTime") if deal else None,
        "dealType": listing.get("type"),
        "hidePrice": bool(listing.get("violatesMAP")),
        "isDeal": bool(deal) or (savings.get("percentage") or 0) >= 10,
    }


# ----------------------------------------------------------------- main
def main():
    config = json.loads(CONFIG_PATH.read_text())
    env = os.environ
    missing = [k for k in ("AMAZON_CREDENTIAL_ID", "AMAZON_CREDENTIAL_SECRET",
                           "AMAZON_PARTNER_TAG") if not env.get(k)]
    if missing:
        sys.exit(f"Missing environment variables: {', '.join(missing)}")

    api = CreatorsApi(
        env["AMAZON_CREDENTIAL_ID"], env["AMAZON_CREDENTIAL_SECRET"],
        env.get("AMAZON_CREDENTIAL_VERSION", "3.1").strip(),
        env["AMAZON_PARTNER_TAG"], config.get("marketplace", "www.amazon.com"),
    )

    old = {}
    if DATA_PATH.exists():
        try:
            old = {p["asin"]: p for p in json.loads(DATA_PATH.read_text()).get("products", [])}
        except (json.JSONDecodeError, KeyError):
            log("Existing products.json unreadable; starting fresh.")

    stamp = now_iso()
    fresh = {}      # asin -> product found in this run
    errors = 0

    # 1. Searches and pinned ASINs, per category
    for cat in config["categories"]:
        name = cat["name"]
        for kw in cat.get("keywords", []):
            for page in range(1, config.get("pagesPerKeyword", 1) + 1):
                try:
                    items = api.search_items(kw, cat.get("searchIndex"),
                                             config.get("itemsPerSearch", 10), page)
                except RuntimeError as e:
                    errors += 1
                    log(f"Search '{kw}' failed: {e}")
                    break
                log(f"{name} / '{kw}' page {page}: {len(items)} items")
                for it in items:
                    p = to_product(it, name)
                    if p and p["asin"] not in fresh:
                        fresh[p["asin"]] = p
        if cat.get("asins"):
            try:
                for it in api.get_items(cat["asins"]):
                    p = to_product(it, name)
                    if p:
                        fresh[p["asin"]] = p
            except RuntimeError as e:
                errors += 1
                log(f"ASIN lookup for {name} failed: {e}")

    # 2. Re-check products already on the site that searches didn't return,
    #    so every price shown is from today.
    recheck = [a for a in old if a not in fresh]
    if recheck:
        log(f"Refreshing {len(recheck)} existing products")
        try:
            for it in api.get_items(recheck):
                prev = old.get(it.get("asin"))
                p = to_product(it, prev["category"] if prev else "Other")
                if p:
                    fresh[p["asin"]] = p
        except RuntimeError as e:
            errors += 1
            log(f"Refresh failed: {e}")

    if not fresh:
        # Don't wipe the site because of a temporary outage.
        sys.exit("No products fetched; keeping the existing file unchanged.")

    # 3. Keep first-seen dates so new items sort to the top
    products = []
    for asin, p in fresh.items():
        prev = old.get(asin)
        p["category"] = prev["category"] if prev else p["category"]
        p["firstSeen"] = prev["firstSeen"] if prev else stamp
        p["lastUpdated"] = stamp
        products.append(p)

    products.sort(key=lambda p: p["firstSeen"], reverse=True)
    products = products[: config.get("maxProducts", 400)]

    new_count = sum(1 for p in products if p["asin"] not in old)
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps({
        "siteName": config.get("siteName", "Daily Finds"),
        "updatedAt": stamp,
        "categories": [c["name"] for c in config["categories"]],
        "products": products,
    }, indent=1, ensure_ascii=False))
    log(f"Saved {len(products)} products ({new_count} new, {errors} errors)")


if __name__ == "__main__":
    main()
