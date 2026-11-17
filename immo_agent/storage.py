import csv
import json
import sqlite3
from pathlib import Path

from .models import Listing

COLUMNS = list(Listing.__dataclass_fields__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    "listing_id" TEXT PRIMARY KEY,
    "source" TEXT NOT NULL,
    "url" TEXT UNIQUE NOT NULL,
    "title" TEXT,
    "transaction" TEXT,
    "price" REAL,
    "currency" TEXT,
    "price_per_m2" REAL,
    "city" TEXT,
    "postal_code" TEXT,
    "address" TEXT,
    "surface_m2" REAL,
    "rooms" INTEGER,
    "bedrooms" INTEGER,
    "bathrooms" INTEGER,
    "description" TEXT,
    "images" TEXT,
    "published_at" TEXT,
    "scraped_at" TEXT
)
"""


class Storage:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def save(self, listing: Listing) -> bool:
        data = listing.to_dict()
        data["images"] = json.dumps(data.get("images") or [], ensure_ascii=False)
        columns = ", ".join(f'"{key}"' for key in data.keys())
        placeholders = ", ".join("?" for _ in data)
        cursor = self.conn.execute(
            f"INSERT OR IGNORE INTO listings ({columns}) VALUES ({placeholders})",
            tuple(data.values()),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def exists(self, url: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM listings WHERE url = ? LIMIT 1", (url,)
        ).fetchone()
        return row is not None

    def count(self, source=None) -> int:
        if source:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM listings WHERE source = ?", (source,)
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) AS n FROM listings").fetchone()
        return row["n"]

    def _row_to_dict(self, row):
        data = dict(row)
        try:
            data["images"] = json.loads(data.get("images") or "[]")
        except json.JSONDecodeError:
            data["images"] = []
        return data

    def query(
        self,
        source=None,
        transaction=None,
        city=None,
        postal_code=None,
        min_price=None,
        max_price=None,
        min_surface=None,
        max_surface=None,
        limit=None,
    ):
        clauses, params = [], []
        if source:
            clauses.append("source = ?")
            params.append(source)
        if transaction:
            clauses.append('"transaction" = ?')
            params.append(transaction)
        if city:
            clauses.append("city LIKE ?")
            params.append(f"%{city}%")
        if postal_code:
            clauses.append("postal_code = ?")
            params.append(postal_code)
        if min_price is not None:
            clauses.append("price >= ?")
            params.append(min_price)
        if max_price is not None:
            clauses.append("price <= ?")
            params.append(max_price)
        if min_surface is not None:
            clauses.append("surface_m2 >= ?")
            params.append(min_surface)
        if max_surface is not None:
            clauses.append("surface_m2 <= ?")
            params.append(max_surface)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM listings{where} ORDER BY scraped_at DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def stats(self):
        total = self.count()
        by_source = {
            row["source"]: row["n"]
            for row in self.conn.execute(
                "SELECT source, COUNT(*) AS n FROM listings GROUP BY source"
            ).fetchall()
        }
        by_transaction = {
            row["transaction"]: row["n"]
            for row in self.conn.execute(
                'SELECT "transaction", COUNT(*) AS n FROM listings GROUP BY "transaction"'
            ).fetchall()
        }
        price_row = self.conn.execute(
            "SELECT MIN(price) AS min_price, MAX(price) AS max_price, AVG(price) AS avg_price FROM listings"
        ).fetchone()
        return {
            "total": total,
            "by_source": by_source,
            "by_transaction": by_transaction,
            "price_min": price_row["min_price"],
            "price_max": price_row["max_price"],
            "price_avg": price_row["avg_price"],
        }

    def export_csv(self, path, **filters):
        rows = self.query(**filters)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            for row in rows:
                row = dict(row)
                row["images"] = " | ".join(row.get("images") or [])
                writer.writerow(row)
        return len(rows)

    def export_json(self, path, **filters):
        rows = self.query(**filters)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False, indent=2)
        return len(rows)

    def close(self):
        self.conn.close()
