import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

LISTING_TYPES = {
    "RealEstateListing",
    "Residence",
    "Apartment",
    "House",
    "SingleFamilyResidence",
    "Condominium",
    "Townhouse",
    "Product",
    "Offer",
}
NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def _flatten(data):
    if isinstance(data, list):
        nodes = []
        for item in data:
            nodes.extend(_flatten(item))
        return nodes
    if isinstance(data, dict):
        graph = data.get("@graph")
        if isinstance(graph, list):
            return _flatten(graph)
        return [data]
    return []


def load_jsonld_nodes(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    nodes = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text()
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        nodes.extend(_flatten(data))
    return nodes


def _types(node):
    value = node.get("@type", [])
    if isinstance(value, str):
        return {value}
    return set(value) if isinstance(value, list) else set()


def _unwrap(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _number(value):
    value = _unwrap(value)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = NUMBER_RE.search(str(value))
    if not match:
        return None
    return float(match.group(0).replace(",", "."))


def _int(value):
    number = _number(value)
    return int(number) if number is not None else None


def _text(value):
    value = _unwrap(value)
    return str(value).strip() if value is not None else ""


def _price_from_offer(offer):
    if not isinstance(offer, dict):
        return None, "EUR"
    price = offer.get("price")
    if price is None and isinstance(offer.get("lowPrice"), (int, float, str)):
        price = offer.get("lowPrice")
    spec = offer.get("priceSpecification")
    if price is None and isinstance(spec, dict):
        price = spec.get("price")
    return _number(price), str(offer.get("priceCurrency", "EUR"))


def _offers(node):
    offers = node.get("offers")
    if isinstance(offers, list):
        return offers
    if offers is not None:
        return [offers]
    return []


def _address(node):
    addr = _unwrap(node.get("address"))
    if isinstance(addr, dict):
        return {
            "address": _text(addr.get("streetAddress")),
            "city": _text(addr.get("addressLocality")),
            "postal_code": _text(addr.get("postalCode")),
        }
    return {"address": _text(addr), "city": "", "postal_code": ""}


def _surface(node):
    size = _unwrap(node.get("floorSize") or node.get("size"))
    if isinstance(size, dict):
        return _number(size.get("value"))
    return _number(size)


def _images(node):
    raw = node.get("image")
    if raw is None:
        raw = node.get("images") or node.get("photo")
    if isinstance(raw, dict):
        raw = raw.get("url") or raw.get("contentUrl")
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        out = []
        for item in raw:
            if isinstance(item, dict):
                item = item.get("url") or item.get("contentUrl")
            if item:
                out.append(str(item))
        return out
    return []


def _node_to_listing(node, source, base_url):
    price, currency = None, "EUR"
    for offer in _offers(node):
        price, currency = _price_from_offer(offer)
        if price is not None:
            break
    addr = _address(node)
    url = _text(node.get("url"))
    if url:
        url = urljoin(base_url, url)
    images = [
        urljoin(base_url, img) if not img.startswith("http") else img
        for img in _images(node)
    ]
    return {
        "source": source,
        "url": url,
        "title": _text(node.get("name")),
        "price": price,
        "currency": currency,
        "address": addr["address"],
        "city": addr["city"],
        "postal_code": addr["postal_code"],
        "surface_m2": _surface(node),
        "rooms": _int(node.get("numberOfRooms")),
        "bedrooms": _int(node.get("numberOfBedrooms")),
        "bathrooms": _int(node.get("numberOfBathrooms")),
        "description": _text(node.get("description")),
        "images": images,
        "published_at": _text(node.get("datePosted") or node.get("datePublished")),
    }


def parse_listings(html_text, source, base_url):
    listings = []
    for node in load_jsonld_nodes(html_text):
        if not isinstance(node, dict):
            continue
        if (_types(node) & LISTING_TYPES) or _offers(node):
            listing = _node_to_listing(node, source, base_url)
            if listing["url"] or listing["title"]:
                listings.append(listing)
    return listings


def extract_listing_urls(html_text, base_url):
    urls = []
    seen = set()
    for node in load_jsonld_nodes(html_text):
        if not isinstance(node, dict) or "ItemList" not in _types(node):
            continue
        elements = node.get("itemListElement") or []
        if isinstance(elements, dict):
            elements = [elements]
        for item in elements:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not url and isinstance(item.get("item"), dict):
                url = item["item"].get("url")
            if url:
                url = urljoin(base_url, str(url))
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
    return urls
