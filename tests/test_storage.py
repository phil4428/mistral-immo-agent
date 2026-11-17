import csv
import json
import tempfile
import unittest
from pathlib import Path

from immo_agent.models import Listing
from immo_agent.storage import Storage


def make_listing(url="https://demo.immo/annonce/1", price=1250.0, city="Paris", transaction="location"):
    return Listing(
        source="demo",
        url=url,
        title="Appartement 2 pieces",
        transaction=transaction,
        price=price,
        city=city,
        postal_code="75011",
        surface_m2=45.0,
        rooms=2,
        images=["https://demo.immo/img/1.jpg"],
    )


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        self.storage = Storage(self.db_path)

    def tearDown(self):
        self.storage.close()
        self.tmp.cleanup()

    def test_save_and_dedup(self):
        self.assertTrue(self.storage.save(make_listing()))
        self.assertFalse(self.storage.save(make_listing()))
        self.assertEqual(self.storage.count(), 1)
        self.assertTrue(self.storage.exists("https://demo.immo/annonce/1"))
        self.assertFalse(self.storage.exists("https://demo.immo/annonce/99"))

    def test_listing_id_stable(self):
        listing = make_listing()
        self.assertEqual(listing.listing_id, make_listing().listing_id)
        self.assertEqual(len(listing.listing_id), 16)

    def test_query_filters(self):
        self.storage.save(make_listing(url="https://demo.immo/annonce/1", price=1250.0, city="Paris"))
        self.storage.save(make_listing(url="https://demo.immo/annonce/2", price=850000.0, city="Lyon", transaction="vente"))
        self.assertEqual(len(self.storage.query()), 2)
        self.assertEqual(len(self.storage.query(transaction="vente")), 1)
        self.assertEqual(len(self.storage.query(city="paris")), 1)
        self.assertEqual(len(self.storage.query(max_price=2000)), 1)
        self.assertEqual(len(self.storage.query(min_surface=100)), 0)
        row = self.storage.query(transaction="location")[0]
        self.assertEqual(row["images"], ["https://demo.immo/img/1.jpg"])

    def test_stats(self):
        self.storage.save(make_listing(price=1000.0))
        self.storage.save(make_listing(url="https://demo.immo/annonce/2", price=3000.0, transaction="vente"))
        stats = self.storage.stats()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["by_source"], {"demo": 2})
        self.assertEqual(stats["by_transaction"], {"location": 1, "vente": 1})
        self.assertEqual(stats["price_min"], 1000.0)
        self.assertEqual(stats["price_max"], 3000.0)

    def test_export(self):
        self.storage.save(make_listing())
        csv_path = Path(self.tmp.name) / "out.csv"
        json_path = Path(self.tmp.name) / "out.json"
        self.assertEqual(self.storage.export_csv(csv_path), 1)
        self.assertEqual(self.storage.export_json(json_path), 1)
        with open(csv_path, encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["city"], "Paris")
        data = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(data[0]["price"], 1250.0)
        self.assertEqual(data[0]["images"], ["https://demo.immo/img/1.jpg"])


if __name__ == "__main__":
    unittest.main()
