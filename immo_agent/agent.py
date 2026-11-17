from urllib.parse import urljoin

from .fetch import FetchError, PoliteFetcher
from .models import Listing
from .parsers import html as html_parser
from .parsers import jsonld
from .sites import build_search_url, load_sites
from .storage import Storage

TRANSACTION_HINTS_LOCATION = ("location", "louer", "loué", "à louer", "/mois", "par mois", "mensuel")
TRANSACTION_HINTS_VENTE = ("vendre", "vente", "vendu", "acquéreur", "acheteur")


def guess_transaction(*texts, default=""):
    blob = " ".join(t or "" for t in texts).lower()
    if any(hint in blob for hint in TRANSACTION_HINTS_LOCATION):
        return "location"
    if any(hint in blob for hint in TRANSACTION_HINTS_VENTE):
        return "vente"
    return default


class Agent:
    def __init__(self, sites_path=None, sites=None, db_path="listings.db", fetcher=None):
        if sites is None:
            sites = load_sites(sites_path or "config/sites.yaml")
        self.sites = sites
        self.storage = Storage(db_path)
        self._fetcher = fetcher

    def _get_fetcher(self, site):
        if self._fetcher is not None:
            return self._fetcher
        return PoliteFetcher(delay=site.delay, respect_robots=site.respect_robots)

    def _collect_cards(self, site, page_html, page_url):
        cards = []
        if site.parser == "html" and site.list_items:
            cards = html_parser.extract_items(
                page_html, site.list_items, site.list_fields, page_url
            )
        if not cards:
            cards = [
                {"url": url}
                for url in jsonld.extract_listing_urls(page_html, page_url)
            ]
        if not cards and site.list_items:
            cards = html_parser.extract_items(
                page_html, site.list_items, site.list_fields, page_url
            )
        seen = set()
        unique = []
        for card in cards:
            url = card.get("url")
            if url and url not in seen:
                seen.add(url)
                unique.append(card)
        return unique

    def _build_listing(self, site, fetcher, card):
        listing_url = card["url"]
        data = {}
        if site.visit_details:
            page_html = fetcher.get(listing_url)
            parsed = jsonld.parse_listings(page_html, site.name, listing_url)
            data = next(
                (p for p in parsed if not p.get("url") or p["url"] == listing_url),
                parsed[0] if parsed else {},
            )
            if not data and site.detail_fields:
                data = html_parser.extract_page_fields(
                    page_html, site.detail_fields, listing_url
                )
        else:
            data = dict(card)
        if not data:
            return None
        data["source"] = site.name
        data["url"] = listing_url
        if not data.get("transaction"):
            data["transaction"] = guess_transaction(
                data.get("title"), data.get("description"), default=site.default_transaction
            )
        if data.get("price") and data.get("surface_m2"):
            data["price_per_m2"] = round(data["price"] / data["surface_m2"], 2)
        images = data.get("images") or []
        if isinstance(images, str):
            images = [images]
        data["images"] = [
            urljoin(listing_url, img) if not str(img).startswith("http") else img
            for img in images
        ]
        return Listing.from_dict(data)

    @staticmethod
    def _matches(listing, filters):
        if not filters:
            return True
        if filters.get("city") and filters["city"].lower() not in (listing.city or "").lower():
            return False
        if filters.get("transaction") and listing.transaction != filters["transaction"]:
            return False
        if filters.get("postal_code") and listing.postal_code != filters["postal_code"]:
            return False
        if filters.get("min_price") is not None and (
            listing.price is None or listing.price < filters["min_price"]
        ):
            return False
        if filters.get("max_price") is not None and (
            listing.price is None or listing.price > filters["max_price"]
        ):
            return False
        if filters.get("min_surface") is not None and (
            listing.surface_m2 is None or listing.surface_m2 < filters["min_surface"]
        ):
            return False
        if filters.get("max_surface") is not None and (
            listing.surface_m2 is None or listing.surface_m2 > filters["max_surface"]
        ):
            return False
        return True

    def run(self, site_name, city=None, transaction=None, postal_code=None, max_pages=None, filters=None):
        if site_name not in self.sites:
            raise KeyError(f"site inconnu : {site_name} (configures : {sorted(self.sites)})")
        site = self.sites[site_name]
        fetcher = self._get_fetcher(site)
        max_pages = max_pages or site.max_pages
        stats = {"site": site_name, "pages": 0, "seen": 0, "new": 0, "skipped": 0, "errors": 0}
        page = 1
        while page <= max_pages:
            url = build_search_url(
                site, page=page, city=city, transaction=transaction, postal_code=postal_code
            )
            try:
                page_html = fetcher.get(url)
            except FetchError:
                stats["errors"] += 1
                break
            stats["pages"] += 1
            cards = self._collect_cards(site, page_html, url)
            if not cards:
                break
            for card in cards:
                stats["seen"] += 1
                if self.storage.exists(card["url"]):
                    stats["skipped"] += 1
                    continue
                try:
                    listing = self._build_listing(site, fetcher, card)
                except FetchError:
                    stats["errors"] += 1
                    continue
                if listing is None or not self._matches(listing, filters):
                    stats["skipped"] += 1
                    continue
                if self.storage.save(listing):
                    stats["new"] += 1
            page += 1
        return stats
