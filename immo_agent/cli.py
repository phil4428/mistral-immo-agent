import argparse
import json
import os
import sys

import yaml

from .agent import Agent
from .dvf import DEFAULT_DATASET_API, DVFClient, sync_dvf
from .fetch import FetchError, PoliteFetcher
from .sites import load_sites
from .storage import Storage


def _default_config():
    for candidate in ("config/sites.yaml", "config/sites.example.yaml"):
        if os.path.exists(candidate):
            return candidate
    return "config/sites.yaml"


def _load_agent_config(path):
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="immo-agent",
        description="Agent d'extraction d'annonces immobilieres (vente / location) et connecteur DVF",
    )
    parser.add_argument("--config", default=_default_config(), help="Fichier YAML des sites")
    parser.add_argument("--agent-config", default="config/agent.yaml", help="Fichier YAML de l'agent")
    parser.add_argument("--db", default=None, help="Chemin de la base SQLite")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sites", help="Lister les sites configures")

    run_parser = sub.add_parser("run", help="Lancer une extraction web")
    run_parser.add_argument("--site", required=True)
    run_parser.add_argument("--city")
    run_parser.add_argument("--transaction", choices=["vente", "location"])
    run_parser.add_argument("--postal-code")
    run_parser.add_argument("--max-pages", type=int)
    run_parser.add_argument("--min-price", type=float)
    run_parser.add_argument("--max-price", type=float)
    run_parser.add_argument("--min-surface", type=float)
    run_parser.add_argument("--max-surface", type=float)

    export_parser = sub.add_parser("export", help="Exporter les annonces collectees")
    export_parser.add_argument("--csv", help="Chemin du fichier CSV")
    export_parser.add_argument("--json", help="Chemin du fichier JSON")
    export_parser.add_argument("--site", help="Filtrer par source (site ou 'dvf')")
    export_parser.add_argument("--transaction", choices=["vente", "location"])
    export_parser.add_argument("--city")

    stats_parser = sub.add_parser("stats", help="Afficher des statistiques sur la base")
    stats_parser.add_argument("--site")

    dvf_parser = sub.add_parser("dvf", help="Synchroniser les ventes DVF (open data data.gouv.fr)")
    dvf_parser.add_argument("--code-postal")
    dvf_parser.add_argument("--code-commune", help="Code INSEE de la commune (5 chiffres)")
    dvf_parser.add_argument("--nature", help="Nature de mutation (ex. Vente)")
    dvf_parser.add_argument("--type-local", help="Type de local (Appartement, Maison, ...)")
    dvf_parser.add_argument("--date-min", help="Date de mutation min (AAAA-MM-JJ)")
    dvf_parser.add_argument("--date-max", help="Date de mutation max (AAAA-MM-JJ)")
    dvf_parser.add_argument("--min-price", type=float)
    dvf_parser.add_argument("--max-price", type=float)
    dvf_parser.add_argument("--min-surface", type=float)
    dvf_parser.add_argument("--max-surface", type=float)
    dvf_parser.add_argument("--year", help="Annnee du fichier DVF (defaut : plus recent)")
    dvf_parser.add_argument("--all-history", action="store_true", help="Utiliser le fichier unique 2021-2026 (tres volumineux)")
    dvf_parser.add_argument("--max-rows", type=int, help="Nombre max de mutations importees")
    dvf_parser.add_argument("--file", help="Fichier DVF local (CSV ou CSV.GZ telecharge dans le navigateur sur data.gouv.fr)")

    args = parser.parse_args(argv)

    agent_cfg_path = args.agent_config
    agent_cfg = _load_agent_config(agent_cfg_path) if os.path.exists(agent_cfg_path) else {}
    db_path = args.db or agent_cfg.get("db_path", "listings.db")
    dvf_cfg = agent_cfg.get("dvf", {})

    if args.command == "sites":
        sites = load_sites(args.config)
        for name, site in sites.items():
            print(f"- {name}: {site.base_url} (parser={site.parser}, max_pages={site.max_pages})")
        return 0

    if args.command == "run":
        sites = load_sites(args.config)
        agent = Agent(sites=sites, db_path=db_path)
        filters = {
            key: value
            for key, value in {
                "city": args.city,
                "transaction": args.transaction,
                "postal_code": args.postal_code,
                "min_price": args.min_price,
                "max_price": args.max_price,
                "min_surface": args.min_surface,
                "max_surface": args.max_surface,
            }.items()
            if value is not None
        }
        stats = agent.run(
            args.site,
            city=args.city,
            transaction=args.transaction,
            postal_code=args.postal_code,
            max_pages=args.max_pages,
            filters=filters,
        )
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0

    storage = Storage(db_path)

    if args.command == "export":
        filters = {
            key: value
            for key, value in {
                "source": args.site,
                "transaction": args.transaction,
                "city": args.city,
            }.items()
            if value is not None
        }
        if args.csv:
            count = storage.export_csv(args.csv, **filters)
            print(f"CSV : {args.csv} ({count} annonce(s))")
        if args.json:
            count = storage.export_json(args.json, **filters)
            print(f"JSON : {args.json} ({count} annonce(s))")
        return 0

    if args.command == "stats":
        stats = storage.stats()
        if args.site:
            stats["total_site"] = storage.count(source=args.site)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0

    if args.command == "dvf":
        fetcher = PoliteFetcher(
            delay=agent_cfg.get("delay", 1.0),
            timeout=agent_cfg.get("timeout", 20),
            respect_robots=agent_cfg.get("respect_robots", True),
            user_agent=agent_cfg.get("user_agent", "immo-agent/1.0 (+contact: admin@example.local)"),
        )
        client = DVFClient(fetcher, dataset_api=dvf_cfg.get("dataset_api", DEFAULT_DATASET_API))
        filters = {
            key: value
            for key, value in {
                "code_postal": args.code_postal,
                "code_commune": args.code_commune,
                "nature": args.nature,
                "type_local": args.type_local,
                "date_min": args.date_min,
                "date_max": args.date_max,
                "min_price": args.min_price,
                "max_price": args.max_price,
                "min_surface": args.min_surface,
                "max_surface": args.max_surface,
            }.items()
            if value is not None
        }
        try:
            stats = sync_dvf(
                storage,
                client,
                filters=filters,
                year=args.year,
                resource_url=args.file,
                all_history=args.all_history,
                max_rows=args.max_rows or dvf_cfg.get("max_rows", 500),
            )
        except FetchError as exc:
            print(f"ERREUR : {exc}", file=sys.stderr)
            print(
                "Indice : robots.txt de static.data.gouv.fr interdit /resources aux agents generiques. "
                "Telecharge le fichier CSV.GZ dans ton navigateur sur data.gouv.fr "
                "(jeu 'Demandes de valeurs foncieres geolocalisees') puis relance avec --file <chemin>. "
                "Aucun compte ni cle API n'est necessaire : donnees publiques en licence ouverte.",
                file=sys.stderr,
            )
            return 2
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
