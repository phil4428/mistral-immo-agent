from dataclasses import dataclass, field
from urllib.parse import quote

import yaml


@dataclass
class SiteConfig:
    name: str
    base_url: str
    search_path: str
    parser: str = "jsonld"
    respect_robots: bool = True
    delay: float = 1.0
    max_pages: int = 5
    visit_details: bool = True
    default_transaction: str = ""
    list_items: str = ""
    list_fields: dict = field(default_factory=dict)
    detail_fields: dict = field(default_factory=dict)
    pagination_selector: str = ""


def load_sites(path):
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    sites = {}
    for name, cfg in (data.get("sites") or {}).items():
        cfg = dict(cfg or {})
        cfg["name"] = name
        sites[name] = SiteConfig(**cfg)
    return sites


def build_search_url(site, page=1, city=None, transaction=None, postal_code=None, **extra):
    params = {"page": page}
    if city:
        params["city"] = city
    if transaction:
        params["transaction"] = transaction
    if postal_code:
        params["postal_code"] = postal_code
    params.update(extra)
    quoted = {key: quote(str(value)) for key, value in params.items()}
    path = site.search_path.format(**quoted)
    return site.base_url.rstrip("/") + path
