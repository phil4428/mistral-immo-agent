import csv
import re
import zlib

from .fetch import FetchError
from .models import Listing

DEFAULT_DATASET_API = (
    "https://www.data.gouv.fr/api/1/datasets/demandes-de-valeurs-foncieres-geolocalisees"
)


def _to_float(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _to_int(value):
    number = _to_float(value)
    return int(number) if number is not None else None


def row_matches(row, filters):
    if not filters:
        return True
    if filters.get("code_postal") and row.get("code_postal") != str(filters["code_postal"]):
        return False
    if filters.get("code_commune") and row.get("code_commune") != str(filters["code_commune"]):
        return False
    if filters.get("nature") and filters["nature"].lower() not in (row.get("nature_mutation") or "").lower():
        return False
    if filters.get("type_local") and filters["type_local"].lower() != (row.get("type_local") or "").lower():
        return False
    date = row.get("date_mutation") or ""
    if filters.get("date_min") and (not date or date < filters["date_min"]):
        return False
    if filters.get("date_max") and (not date or date > filters["date_max"]):
        return False
    price = _to_float(row.get("valeur_fonciere"))
    if filters.get("min_price") is not None and (price is None or price < filters["min_price"]):
        return False
    if filters.get("max_price") is not None and (price is None or price > filters["max_price"]):
        return False
    surface = _to_float(row.get("surface_reelle_bati"))
    if filters.get("min_surface") is not None and (surface is None or surface < filters["min_surface"]):
        return False
    if filters.get("max_surface") is not None and (surface is None or surface > filters["max_surface"]):
        return False
    return True


def row_to_listing(row):
    price = _to_float(row.get("valeur_fonciere"))
    surface = _to_float(row.get("surface_reelle_bati"))
    pieces = _to_int(row.get("nombre_pieces_principales"))
    nature = (row.get("nature_mutation") or "").strip()
    type_local = (row.get("type_local") or "").strip()
    city = (row.get("nom_commune") or "").strip()
    date = row.get("date_mutation") or ""
    address = " ".join(
        part for part in [row.get("adresse_numero"), row.get("adresse_suffixe"), row.get("adresse_nom_voie")] if part
    )
    description = f"{nature or 'Mutation'} du {date} - {type_local or 'bien'}"
    if surface:
        description += f", {surface:g} m2"
    if pieces:
        description += f", {pieces} piece(s) principale(s)"
    if row.get("id_parcelle"):
        description += f" - parcelle {row['id_parcelle']}"
    data = {
        "source": "dvf",
        "url": f"dvf://mutation/{row.get('id_mutation') or ''}",
        "title": f"{type_local or 'Bien'} - {city}".strip(" -"),
        "transaction": "vente",
        "price": price,
        "currency": "EUR",
        "city": city,
        "postal_code": (row.get("code_postal") or "").strip(),
        "address": address,
        "surface_m2": surface,
        "rooms": pieces,
        "description": description,
        "published_at": date,
    }
    if price and surface:
        data["price_per_m2"] = round(price / surface, 2)
    return Listing.from_dict(data)


class DVFClient:
    def __init__(self, fetcher, dataset_api=DEFAULT_DATASET_API):
        self.fetcher = fetcher
        self.dataset_api = dataset_api

    def resources(self):
        data = self.fetcher.get_json(self.dataset_api)
        return [
            resource
            for resource in data.get("resources", [])
            if (resource.get("url") or "").startswith("https://static.data.gouv.fr/")
            and resource["url"].endswith(".csv.gz")
        ]

    def resolve_resource(self, year=None, all_history=False):
        candidates = self.resources()
        if not candidates:
            raise FetchError("aucune ressource CSV .csv.gz trouvee sur data.gouv.fr")
        if all_history:
            picked = [r for r in candidates if r["url"].endswith("dvf.csv.gz")]
        elif year:
            picked = [r for r in candidates if f"full-{year}" in r["url"]]
        else:
            def sort_key(resource):
                match = re.search(r"full-(\d{4})(?:-s(\d))?", resource["url"])
                return (int(match.group(1)), int(match.group(2) or 0)) if match else (0, 0)
            picked = [max(candidates, key=sort_key)]
        if not picked:
            raise FetchError(f"pas de ressource DVF pour year={year}, all_history={all_history}")
        return picked[0]["url"]

    def stream_rows(self, source):
        is_remote = source.startswith(("http://", "https://"))
        file_handle = None
        if is_remote:
            response = self.fetcher.open_stream(source, timeout=600)
            if response.status_code >= 400:
                raise FetchError(f"HTTP {response.status_code} pour {source}")
            chunks = response.iter_content(chunk_size=1 << 20)
            gz = source.endswith(".gz")
        else:
            file_handle = open(source, "rb")
            gz = file_handle.read(2) == b"\x1f\x8b"
            file_handle.seek(0)
            chunks = iter(lambda: file_handle.read(1 << 20), b"")
        try:
            decoder = zlib.decompressobj(31) if gz else None
            buffer = b""

            def lines():
                nonlocal buffer
                for chunk in chunks:
                    if not chunk:
                        continue
                    buffer += decoder.decompress(chunk) if decoder else chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        yield line.decode("utf-8", errors="replace").rstrip("\r")
                if decoder:
                    buffer += decoder.flush()
                if buffer:
                    yield buffer.decode("utf-8", errors="replace").rstrip("\r")

            reader = csv.reader(lines())
            header = next(reader, None)
            if not header:
                return
            for row in reader:
                if len(row) < len(header):
                    continue
                yield dict(zip(header, row))
        finally:
            if file_handle is not None:
                file_handle.close()


def sync_dvf(storage, client, filters=None, year=None, resource_url=None, all_history=False, max_rows=500):
    url = resource_url or client.resolve_resource(year=year, all_history=all_history)
    stats = {"resource": url, "scanned": 0, "matched": 0, "new": 0, "skipped": 0}
    best = {}
    for row in client.stream_rows(url):
        stats["scanned"] += 1
        if not row_matches(row, filters):
            continue
        mutation_id = row.get("id_mutation") or f"row-{stats['scanned']}"
        current = best.get(mutation_id)
        if current is None or (_to_float(row.get("surface_reelle_bati")) or 0) > (
            _to_float(current.get("surface_reelle_bati")) or 0
        ):
            best[mutation_id] = row
        if len(best) >= max_rows:
            break
    stats["matched"] = len(best)
    for row in best.values():
        listing = row_to_listing(row)
        if storage.exists(listing.url):
            stats["skipped"] += 1
        elif storage.save(listing):
            stats["new"] += 1
    return stats
