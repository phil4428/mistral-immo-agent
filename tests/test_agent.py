import tempfile
import unittest
from pathlib import Path

from immo_agent.agent import Agent, guess_transaction
from immo_agent.fetch import FetchError
from immo_agent.sites import load_sites

FIXTURES = Path(__file__).parent / "fixtures"

CONFIG_YAML = """
sites:
  demo:
    base_url: "https://demo.immo"
    search_path: "/annonces?page={page}"
    parser: jsonld
    respect_robots: false
    max_pages: 5
    visit_details: true
"""


def read_fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.requests = []

    def can_fetch(self, url):
        return True

    def get(self, url):
        self.requests.append(url)
        if url not in self.pages:
            raise FetchError(f"404 {url}")
        return self.pages[url]


def build_fetcher():
    return FakeFetcher(
        {
            "https://demo.immo/annonces?page=1": read_fixture("list_jsonld.html"),
            "https://demo.immo/annonces?page=2": read_fixture("list_empty.html"),
            "https://demo.immo/annonce/1": read_fixture("detail1_jsonld.html"),
            "https://demo.immo/annonce/2": read_fixture("detail2_jsonld.html"),
        }
    )


class TestGuessTransaction(unittest.TestCase):
    def test_hints(self):
        self.assertEqual(guess_transaction("Bel appartement à louer, 1250 €/mois"), "location")
        self.assertEqual(guess_transaction("Maison familiale à vendre"), "vente")
        self.assertEqual(guess_transaction("Rien ici", default="vente"), "vente")
        self.assertEqual(guess_transaction("Rien ici"), "")


class TestAgent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "sites.yaml"
        self.config_path.write_text(CONFIG_YAML, encoding="utf-8")
        self.db_path = str(Path(self.tmp.name) / "listings.db")
        self.sites = load_sites(self.config_path)

    def tearDown(self):
        self.tmp.cleanup()

    def make_agent(self, fetcher=None):
        return Agent(sites=self.sites, db_path=self.db_path, fetcher=fetcher or build_fetcher())

    def test_run_collects_listings(self):
        agent = self.make_agent()
        stats = agent.run("demo", max_pages=5)
        self.assertEqual(stats["pages"], 2)
        self.assertEqual(stats["seen"], 2)
        self.assertEqual(stats["new"], 2)
        self.assertEqual(stats["errors"], 0)
        rows = agent.storage.query()
        self.assertEqual(len(rows), 2)
        by_url = {row["url"]: row for row in rows}
        paris = by_url["https://demo.immo/annonce/1"]
        self.assertEqual(paris["transaction"], "location")
        self.assertEqual(paris["price"], 1250.0)
        self.assertEqual(paris["price_per_m2"], round(1250 / 45, 2))
        self.assertEqual(paris["city"], "Paris")
        lyon = by_url["https://demo.immo/annonce/2"]
        self.assertEqual(lyon["transaction"], "vente")
        self.assertEqual(lyon["price"], 850000.0)

    def test_rerun_is_idempotent(self):
        agent = self.make_agent()
        agent.run("demo")
        stats = agent.run("demo")
        self.assertEqual(stats["new"], 0)
        self.assertEqual(stats["skipped"], 2)
        self.assertEqual(agent.storage.count(), 2)

    def test_price_filter(self):
        agent = self.make_agent()
        stats = agent.run("demo", filters={"max_price": 2000})
        self.assertEqual(stats["new"], 1)
        rows = agent.storage.query()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["city"], "Paris")

    def test_transaction_filter(self):
        agent = self.make_agent()
        stats = agent.run("demo", filters={"transaction": "vente"})
        self.assertEqual(stats["new"], 1)
        rows = agent.storage.query()
        self.assertEqual(rows[0]["city"], "Lyon")

    def test_unknown_site_raises(self):
        agent = self.make_agent()
        with self.assertRaises(KeyError):
            agent.run("inconnu")

    def test_fetch_error_counted(self):
        fetcher = build_fetcher()
        del fetcher.pages["https://demo.immo/annonce/2"]
        agent = self.make_agent(fetcher=fetcher)
        stats = agent.run("demo")
        self.assertEqual(stats["new"], 1)
        self.assertEqual(stats["errors"], 1)


if __name__ == "__main__":
    unittest.main()
