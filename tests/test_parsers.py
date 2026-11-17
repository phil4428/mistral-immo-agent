import unittest
from pathlib import Path

from immo_agent.parsers import html as html_parser
from immo_agent.parsers import jsonld

FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestParseNumber(unittest.TestCase):
    def test_plain_prices(self):
        self.assertEqual(html_parser.parse_number("750 €/mois"), 750.0)
        self.assertEqual(html_parser.parse_number("320 000 €"), 320000.0)
        self.assertEqual(html_parser.parse_number("22 m²"), 22.0)

    def test_french_decimal(self):
        self.assertEqual(html_parser.parse_number("1 500,50 €"), 1500.5)
        self.assertEqual(html_parser.parse_number("850.000 €"), 850000.0)

    def test_no_number(self):
        self.assertIsNone(html_parser.parse_number("sur devis"))
        self.assertIsNone(html_parser.parse_number(None))


class TestJsonLdParser(unittest.TestCase):
    def test_parse_detail_listing(self):
        html_text = read_fixture("detail1_jsonld.html")
        listings = jsonld.parse_listings(html_text, "demo", "https://demo.immo/annonce/1")
        self.assertEqual(len(listings), 1)
        listing = listings[0]
        self.assertEqual(listing["title"], "Appartement 2 pieces - Paris 11e")
        self.assertEqual(listing["price"], 1250.0)
        self.assertEqual(listing["currency"], "EUR")
        self.assertEqual(listing["city"], "Paris")
        self.assertEqual(listing["postal_code"], "75011")
        self.assertEqual(listing["address"], "12 rue de la Roquette")
        self.assertEqual(listing["surface_m2"], 45.0)
        self.assertEqual(listing["rooms"], 2)
        self.assertEqual(listing["bedrooms"], 1)
        self.assertEqual(listing["bathrooms"], 1)
        self.assertEqual(listing["images"], ["https://demo.immo/img/1a.jpg", "https://demo.immo/img/1b.jpg"])
        self.assertEqual(listing["published_at"], "2025-01-10")
        self.assertEqual(listing["url"], "https://demo.immo/annonce/1")

    def test_parse_house_vente(self):
        html_text = read_fixture("detail2_jsonld.html")
        listings = jsonld.parse_listings(html_text, "demo", "https://demo.immo/annonce/2")
        self.assertEqual(listings[0]["price"], 850000.0)
        self.assertEqual(listings[0]["surface_m2"], 120.0)
        self.assertEqual(listings[0]["city"], "Lyon")

    def test_extract_listing_urls(self):
        html_text = read_fixture("list_jsonld.html")
        urls = jsonld.extract_listing_urls(html_text, "https://demo.immo/annonces?page=1")
        self.assertEqual(
            urls,
            ["https://demo.immo/annonce/1", "https://demo.immo/annonce/2"],
        )

    def test_extract_listing_urls_empty(self):
        html_text = read_fixture("list_empty.html")
        self.assertEqual(jsonld.extract_listing_urls(html_text, "https://demo.immo"), [])

    def test_invalid_json_ignored(self):
        html_text = '<script type="application/ld+json">{invalid json}</script><p>ok</p>'
        self.assertEqual(jsonld.parse_listings(html_text, "demo", "https://x"), [])


LIST_FIELDS = {
    "title": {"selector": "h2 a", "attr": "text"},
    "url": {"selector": "h2 a", "attr": "href"},
    "price": {"selector": ".prix", "attr": "text", "type": "float"},
    "city": {"selector": ".ville", "attr": "text"},
    "surface_m2": {"selector": ".surface", "attr": "text", "type": "float"},
}

DETAIL_FIELDS = {
    "title": {"selector": "h1", "attr": "text"},
    "price": {"selector": ".prix", "attr": "text", "type": "float"},
    "address": {"selector": ".adresse", "attr": "text"},
    "city": {"selector": ".adresse", "attr": "text", "regex": ",\\s*(?:\\d{5}\\s*)?([^,]+)$"},
    "postal_code": {"selector": ".adresse", "attr": "text", "regex": "(\\d{5})"},
    "surface_m2": {"selector": ".surface", "attr": "text", "type": "float"},
    "rooms": {"selector": ".caracteristiques", "attr": "text", "regex": "(\\d+)\\s*pi[eè]ces", "type": "int"},
    "bedrooms": {"selector": ".caracteristiques", "attr": "text", "regex": "(\\d+)\\s*chambres?", "type": "int"},
    "bathrooms": {"selector": ".caracteristiques", "attr": "text", "regex": "(\\d+)\\s*salle", "type": "int"},
    "description": {"selector": ".description", "attr": "text"},
    "currency": {"value": "EUR"},
    "images": {"selector": ".galerie img", "attr": "src", "multiple": True},
}


class TestHtmlParser(unittest.TestCase):
    def test_extract_items(self):
        html_text = read_fixture("list_html.html")
        items = html_parser.extract_items(
            html_text, "article.annonce", LIST_FIELDS, "https://www.example-portail.fr/annonces"
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["url"], "https://www.example-portail.fr/annonce/10")
        self.assertEqual(items[0]["title"], "Studio - Bordeaux")
        self.assertEqual(items[0]["price"], 750.0)
        self.assertEqual(items[0]["surface_m2"], 22.0)
        self.assertEqual(items[1]["price"], 320000.0)
        self.assertEqual(items[1]["city"], "Nantes")

    def test_extract_page_fields(self):
        html_text = read_fixture("detail_html.html")
        data = html_parser.extract_page_fields(
            html_text, DETAIL_FIELDS, "https://www.example-portail.fr/annonce/10"
        )
        self.assertEqual(data["title"], "Appartement 3 pieces - Toulouse")
        self.assertEqual(data["price"], 980.0)
        self.assertEqual(data["postal_code"], "31000")
        self.assertEqual(data["surface_m2"], 56.0)
        self.assertEqual(data["rooms"], 3)
        self.assertEqual(data["bedrooms"], 2)
        self.assertEqual(data["bathrooms"], 1)
        self.assertIn("à louer", data["description"])
        self.assertEqual(data["currency"], "EUR")
        self.assertEqual(data["images"], ["/img/a.jpg", "/img/b.jpg"])


if __name__ == "__main__":
    unittest.main()
