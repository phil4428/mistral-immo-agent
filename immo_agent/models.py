import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass
class Listing:
    source: str
    url: str
    title: str = ""
    transaction: str = ""
    price: float | None = None
    currency: str = "EUR"
    price_per_m2: float | None = None
    city: str = ""
    postal_code: str = ""
    address: str = ""
    surface_m2: float | None = None
    rooms: int | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    description: str = ""
    images: list = field(default_factory=list)
    published_at: str = ""
    scraped_at: str = ""
    listing_id: str = ""

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not self.listing_id:
            self.listing_id = hashlib.sha256(
                f"{self.source}|{self.url}".encode("utf-8")
            ).hexdigest()[:16]

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})
