# immo-agent

Agent d'extraction d'annonces immobilières (vente et location) sur le web, en Python.

Il parcourt les pages de résultats d'un portail immobilier, visite chaque annonce,
extrait les données structurées et les stocke dans une base SQLite (avec déduplication),
puis permet de les exporter en CSV ou JSON.

## Installation

```bash
cd immo-agent
pip install -r requirements.txt
```

Python 3.11+ requis. Dépendances : `requests`, `beautifulsoup4`, `PyYAML`.

## Utilisation

```bash
# Lister les sites configurés
python -m immo_agent sites

# Lancer une extraction
python -m immo_agent run --site demo-jsonld --city paris --transaction location \
    --max-price 1500 --min-surface 20 --max-pages 5

# Voir les statistiques de la base
python -m immo_agent stats

# Exporter
python -m immo_agent export --csv annonces.csv --json annonces.json --transaction location
```

Options de `run` : `--site`, `--city`, `--transaction {vente,location}`,
`--postal-code`, `--max-pages`, `--min-price`, `--max-price`, `--min-surface`,
`--max-surface`. Options globales : `--config` (fichier des sites),
`--agent-config` (fichier de l'agent), `--db` (base SQLite).

## Configuration

Copier `config/sites.example.yaml` en `config/sites.yaml` et l'adapter :

```yaml
sites:
  mon-portail:
    base_url: "https://www.exemple.fr"
    search_path: "/annonces?type={transaction}&ville={city}&p={page}"
    parser: html            # "jsonld" (défaut) ou "html"
    respect_robots: true    # refuse toute URL interdite par robots.txt
    delay: 2.0              # délai mini entre requêtes vers le même hôte
    max_pages: 5
    visit_details: true     # visite chaque page d'annonce
    default_transaction: location
    list_items: "article.annonce"
    list_fields:
      title: { selector: "h2 a", attr: text }
      url: { selector: "h2 a", attr: href }
      price: { selector: ".prix", attr: text, type: float }
    detail_fields:
      title: { selector: "h1" }
      price: { selector: ".prix", attr: text, type: float }
      city: { selector: ".adresse", attr: text, regex: ",\\s*(?:\\d{5}\\s*)?([^,]+)$" }
      surface_m2: { selector: ".surface", attr: text, type: float }
```

Deux modes de parsing :

- **`jsonld`** (recommandé quand c'est possible) : lit les balises
  `<script type="application/ld+json">` (schema.org `Apartment`, `House`,
  `RealEstateListing`, `Offer`, `ItemList`...). Beaucoup de portails
  immobiliers les embarquent nativement.
- **`html`** : sélecteurs CSS déclarés dans le YAML. Chaque champ accepte
  `selector`, `attr` (`text`, `href`, `src`, ou tout attribut HTML), `regex`
  (prend le groupe 1 si présent) et `type` (`str`, `float`, `int`). Les prix
  au format français sont gérés (`1 500 €`, `850.000 €`, `1 500,50 €`).

Les champs extraits portent les noms du modèle `Listing` (`title`, `price`,
`city`, `postal_code`, `surface_m2`, `rooms`, `bedrooms`, `bathrooms`,
`description`, `images`, `address`...). Le type de transaction (`vente` /
`location`) est déduit du titre et de la description quand il n'est pas
explicite ; `price_per_m2` est calculé automatiquement.

Paramètres généraux dans `config/agent.yaml` : chemin de la base, délai,
timeout, tentatives, user-agent.

## Modèle de données

Table SQLite `listings` : `listing_id` (hash source+URL), `source`, `url`
(unique), `title`, `transaction`, `price`, `currency`, `price_per_m2`,
`city`, `postal_code`, `address`, `surface_m2`, `rooms`, `bedrooms`,
`bathrooms`, `description`, `images` (JSON), `published_at`, `scraped_at`.

## Exemple fonctionnel : books.toscrape.com (site qui autorise le scraping)

[books.toscrape.com](https://books.toscrape.com) est un bac à sable prévu pour
s'entraîner au scraping : aucun `robots.txt` (404 = tout autorisé). La config
`config/sites.books.example.yaml` montre le mode `html` complet :

```bash
python -m immo_agent --config config/sites.books.example.yaml --db demo.db run --site books --max-pages 2
python -m immo_agent --db demo.db export --csv books.csv --json books.json
python -m immo_agent --db demo.db stats
```

Résultat constaté : 2 pages parcourues, 40 annonces extraites (titre, prix en
GBP, description, image, URL absolue), 0 erreur ; un second `run` est
idempotent (0 nouveau, 20 ignorés). Note : les règles de champ acceptent
`value:` (champ statique, ex. `currency: GBP`) et `multiple: true` (liste,
ex. images).

Pour l'immobilier, la plupart des grands portails français (Leboncoin,
SeLoger, PAP, Bien'ici, OuestFrance-Immo) interdisent le crawl de leurs pages
d'annonces dans leur `robots.txt` : ce mécanisme s'applique tel quel à tout
portail qui **autorise** explicitement les robots, sinon passer par les API
officielles ou les données ouvertes (DVF).

## Connecteur DVF (prix de vente réels, open data)

Commande `dvf` : importe les **mutations DVF** (Demandes de Valeurs Foncières,
DGFiP) publiées en open data sur data.gouv.fr, directement dans la même base
SQLite (source `dvf`, transaction `vente`, prix/m² calculé). **Aucun compte ni
clé API n'est nécessaire** : l'API `data.gouv.fr/api/1/` est publique et les
fichiers DVF sont en licence ouverte.

Deux modes :

```bash
# 1) Fichier local (recommandé) : télécharger le CSV.GZ en un clic dans le
#    navigateur sur data.gouv.fr (jeu « Demandes de valeurs foncières
#    géolocalisées », ex. full-2026-s1.csv.gz ~52 Mo ou dvf.csv.gz ~609 Mo),
#    puis :
python -m immo_agent dvf --file dvf.csv.gz --code-postal 75011 --max-rows 500

# 2) Téléchargement direct par l'agent (soumis à robots.txt) :
python -m immo_agent dvf --year 2026 --code-postal 75011
```

Filtres disponibles : `--code-postal`, `--code-commune` (INSEE), `--nature`,
`--type-local`, `--date-min`, `--date-max`, `--min-price`, `--max-price`,
`--min-surface`, `--max-surface`, `--year`, `--all-history`, `--max-rows`.
Le fichier est streamé et décompressé à la volée (gzip détecté automatiquement),
filtré en cours de lecture, et les lignes multi-lots d'une même mutation sont
regroupées (on garde le local de plus grande surface). Les relances sont
idempotentes (dédup par `dvf://mutation/<id>`).

Exemples :

```bash
python -m immo_agent dvf --file dvf.csv.gz --code-postal 75011 --type-local Appartement --date-min 2025-01-01 --min-price 100000 --max-price 600000
python -m immo_agent export --json ventes-paris11.json --site dvf
python -m immo_agent stats --site dvf
```

Note : le `robots.txt` de `static.data.gouv.fr` interdit `/resources` aux
agents génériques, donc le mode 2 refusera le téléchargement (comportement
voulu, avec message d'aide) ; le mode 1 (`--file`) contourne proprement ce
point puisque le fichier est récupéré manuellement. L'API DVF+ du Cerema
(`apidf.cerema.fr/dvf_opendata/mutations/`) est une autre route API officielle
sans clé, utile si elle est joignable depuis votre réseau.

## Éthique et légal

- `respect_robots: true` par défaut : l'agent **refuse de télécharger** toute
  URL déclarée interdite par le `robots.txt` du site.
- Délai configurable entre requêtes, user-agent identifiable, retries avec
  backoff sur 429/5xx : ne pas chercher à contourner les limites de débit.
- Avant de cibler un site réel, vérifier ses **CGU** : de nombreux portails
  interdisent le scraping automatisé. Privilégier leurs API officielles quand
  elles existent.
- Pour les **prix de vente** en France, la source ouverte et légale est la
  base [DVF](https://www.data.gouv.fr/fr/datasets/demandes-de-valeurs-foncieres/)
  (data.gouv.fr).

## Sites à accès restreint (exemple : Leboncoin)

`config/sites.leboncoin.example.yaml` montre le **format** d'une entrée pour
un portail de petites annonces. Même situation pour **efficity.com**
(`config/sites.efficity.example.yaml`) : son `robots.txt` contient
`User-agent: *` + `Disallow: /`, donc **toutes** les pages sont refusées à
l'agent (vérifié : `can_fetch` → `False` pour chaque URL). Ces entrées sont
volontairement inertes tant qu'aucune autorisation écrite n'est obtenue.

Pour un portail de petites annonces (catégories 10 = ventes immobilières,
11 = locations ; `locations=` attend l'identifiant de zone Leboncoin, ex.
`Paris_75056` ; sélecteurs à adapter à la main). **Ne l'utilise pas tel quel
contre leboncoin.fr** : son `robots.txt` interdit l'accès automatisé sans
autorisation spéciale et ses CGU (art. 10.2) interdisent les robots sans
autorisation expresse de LBC France. Avec `respect_robots: true` (laisser ce
réglage), l'agent refusera de télécharger les pages `/recherche/` et
`/annonce/`. Ne désactive pas cette protection pour ce site. Voie conforme :
l'[API partenaire officielle](https://api.leboncoin.fr) (compte professionnel
avec contrat), ou des portails dont le `robots.txt` autorise explicitement les
robots.
- Les annonces peuvent contenir des données personnelles (téléphone,
  email du vendeur) : ne collecte que les champs utiles, et conforme-toi au
  RGPD pour tout stockage/utilisation ultérieur.

## Tests

```bash
python -m unittest discover -s tests -v
```

37 tests couvrent les parseurs (JSON-LD, sélecteurs CSS, parsing des prix),
le stockage SQLite (déduplication, filtres, exports) et le flux complet de
l'agent avec un fetcher simulé (aucun accès réseau).

## Limites et pistes

- Les sites rendus côté client (JavaScript) nécessitent un navigateur
  headless (Playwright/Selenium) : non inclus ici.
- Pas de rotation de proxies : un seul client, rythme lent, conforme
  robots.txt.
- Pour une exécution périodique : lancer `run` via cron/systemd, la
  déduplication par URL rend les relances idempotentes.
