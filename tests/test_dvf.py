import gzip
import tempfile
import unittest
from pathlib import Path

from immo_agent.dvf import DVFClient, row_matches, row_to_listing, sync_dvf
from immo_agent.storage import Storage

HEADER = (
    "id_mutation,date_mutation,numero_disposition,nature_mutation,valeur_fonciere,"
    "adresse_numero,adresse_suffixe,adresse_nom_voie,adresse_code_voie,code_postal,"
    "code_commune,nom_commune,code_departement,id_parcelle,code_type_local,type_local,"
    "surface_reelle_bati,nombre_pieces_principales,surface_terrain,longitude,latitude"
)

ROWS = [
    "2026-1,2026-03-10,000001,Vente,250000.00,12,,RUE DE PARIS,B120,75011,75111,Paris 11e,75,75111000AB0001,1,Appartement,45,2,,2.35,48.86",
    "2026-1,2026-03-10,000001,Vente,250000.00,,,RUE DE PARIS,B120,75011,75111,Paris 11e,75,75111000AB0002,,,,,,,2.35,48.86",
    "2026-2,2026-04-02,000001,Vente,180000.00,18,Z,RUE DE GORREVOD,0200,01190,01305,Pont-de-Vaux,01,01305000AK0123,1,Maison,98,4,,4.94,46.42",
    "2026-3,2026-01-15,000002,Vente,150000.00,3,,ALLEE DES LILAS,C004,75011,75111,Paris 11e,75,75111000CD0007,4,Local commercial,120,,,,2.36,48.87",
]

CSV_TEXT = "\n".join([HEADER] + ROWS) + "\n"

DATASET = {
    "resources": [
        {"title": "DVF 2025", "url": "https://static.data.gouv.fr/resources/x/20261020/full-2025.csv.gz"},
        {"title": "DVF 2026 (1er semestre)", "url": "https://static.data.gouv.fr/resources/x/20261020/full-2026-s1.csv.gz"},
        {"title": "fichier unique", "url": "https://static.data.gouv.fr/resources/x/20261021/dvf.csv.gz"},
        {"title": "doc", "url": "https://static.data.gouv.fr/resources/x/faq.pdf"},
        {"title": "archive", "url": "https://files.data.gouv.fr/geo-dvf/latest/csv/"},
    ]
}


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def iter_content(self, chunk_size=65536):
        yield self._payload


class FakeFetcher:
    def __init__(self, gz_payload, dataset=DATASET):
        self._gz_payload = gz_payload
        self._dataset = dataset
        self.streamed_urls = []

    def can_fetch(self, url):
        return True

    def get_json(self, url):
        return self._dataset

    def open_stream(self, url, timeout=None):
        self.streamed_urls.append(url)
        return FakeResponse(self._gz_payload)


def make_client():
    return DVFClient(FakeFetcher(gzip.compress(CSV_TEXT.encode("utf-8"))))


class TestResolveResource(unittest.TestCase):
    def test_default_picks_latest_year(self):
        client = make_client()
        self.assertIn("full-2026-s1", client.resolve_resource())

    def test_year_selection(self):
        client = make_client()
        self.assertIn("full-2025", client.resolve_resource(year="2025"))

    def test_all_history(self):
        client = make_client()
        self.assertTrue(client.resolve_resource(all_history=True).endswith("dvf.csv.gz"))

    def test_unknown_year_raises(self):
        from immo_agent.fetch import FetchError
        client = make_client()
        with self.assertRaises(FetchError):
            client.resolve_resource(year="1999")


class TestStreamRows(unittest.TestCase):
    def test_stream_parses_all_rows(self):
        client = make_client()
        rows = list(client.stream_rows("https://static.data.gouv.fr/x/full-2026-s1.csv.gz"))
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["code_postal"], "75011")
        self.assertEqual(rows[0]["valeur_fonciere"], "250000.00")

    def test_stream_local_csv_file(self):
        fixture = Path(__file__).parent / "fixtures" / "dvf_sample.csv"
        client = make_client()
        rows = list(client.stream_rows(str(fixture)))
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[1]["code_postal"], "01190")
        self.assertEqual(rows[1]["nom_commune"], "Pont-de-Vaux")

    def test_sync_from_local_file(self):
        fixture = str(Path(__file__).parent / "fixtures" / "dvf_sample.csv")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        storage = Storage(str(Path(tmp.name) / "local.db"))
        self.addCleanup(storage.close)
        stats = sync_dvf(storage, make_client(), filters={"code_postal": "01190"}, resource_url=fixture)
        self.assertEqual(stats["matched"], 2)
        self.assertEqual(stats["new"], 2)
        rows = storage.query(source="dvf")
        self.assertEqual({r["url"] for r in rows}, {"dvf://mutation/2021-2", "dvf://mutation/2021-3"})


class TestRowMatches(unittest.TestCase):
    def setUp(self):
        self.rows = list(make_client().stream_rows("https://static.data.gouv.fr/x/full-2026-s1.csv.gz"))

    def test_code_postal(self):
        rows = [r for r in self.rows if row_matches(r, {"code_postal": "75011"})]
        self.assertEqual(len(rows), 3)

    def test_price_and_type(self):
        rows = [r for r in self.rows if row_matches(r, {"max_price": 200000, "type_local": "Local commercial"})]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id_mutation"], "2026-3")

    def test_date_range(self):
        rows = [r for r in self.rows if row_matches(r, {"date_min": "2026-02-01"})]
        self.assertEqual({r["id_mutation"] for r in rows}, {"2026-1", "2026-2"})

    def test_no_filters_matches_all(self):
        self.assertEqual(sum(1 for r in self.rows if row_matches(r, None)), 4)


class TestRowToListing(unittest.TestCase):
    def test_mapping(self):
        row = list(make_client().stream_rows("https://static.data.gouv.fr/x/full-2026-s1.csv.gz"))[0]
        listing = row_to_listing(row)
        self.assertEqual(listing.source, "dvf")
        self.assertEqual(listing.url, "dvf://mutation/2026-1")
        self.assertEqual(listing.transaction, "vente")
        self.assertEqual(listing.price, 250000.0)
        self.assertEqual(listing.currency, "EUR")
        self.assertEqual(listing.city, "Paris 11e")
        self.assertEqual(listing.postal_code, "75011")
        self.assertEqual(listing.address, "12 RUE DE PARIS")
        self.assertEqual(listing.surface_m2, 45.0)
        self.assertEqual(listing.rooms, 2)
        self.assertEqual(listing.published_at, "2026-03-10")
        self.assertAlmostEqual(listing.price_per_m2, round(250000 / 45, 2))
        self.assertIn("parcelle 75111000AB0001", listing.description)


class TestSyncDvf(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "dvf.db")
        self.storage = Storage(self.db_path)
        self.client = make_client()

    def tearDown(self):
        self.storage.close()
        self.tmp.cleanup()

    def test_sync_groups_by_mutation_and_stores(self):
        stats = sync_dvf(self.storage, self.client, filters={"code_postal": "75011"}, max_rows=10)
        self.assertEqual(stats["scanned"], 4)
        self.assertEqual(stats["matched"], 2)
        self.assertEqual(stats["new"], 2)
        rows = self.storage.query(source="dvf")
        self.assertEqual(len(rows), 2)
        by_url = {r["url"]: r for r in rows}
        self.assertEqual(by_url["dvf://mutation/2026-1"]["surface_m2"], 45.0)
        self.assertEqual(by_url["dvf://mutation/2026-3"]["price"], 150000.0)

    def test_resync_is_idempotent(self):
        sync_dvf(self.storage, self.client, filters={"code_postal": "75011"}, max_rows=10)
        stats = sync_dvf(self.storage, self.client, filters={"code_postal": "75011"}, max_rows=10)
        self.assertEqual(stats["new"], 0)
        self.assertEqual(stats["skipped"], 2)
        self.assertEqual(self.storage.count(source="dvf"), 2)

    def test_max_rows_limit(self):
        stats = sync_dvf(self.storage, self.client, filters=None, max_rows=1)
        self.assertEqual(stats["matched"], 1)
        self.assertEqual(stats["new"], 1)


if __name__ == "__main__":
    unittest.main()
