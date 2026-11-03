"""Build the local synthetic retail database from the versioned SQL files."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_database(output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(output) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            DROP TABLE IF EXISTS fact_order_line;
            DROP TABLE IF EXISTS fact_order;
            DROP TABLE IF EXISTS dim_product;
            DROP TABLE IF EXISTS dim_store;
            DROP TABLE IF EXISTS dim_date;
            """
        )
        connection.executescript((ROOT / "data" / "schema.sql").read_text(encoding="utf-8"))
        connection.executescript((ROOT / "data" / "seed.sql").read_text(encoding="utf-8"))
        violations = list(connection.execute("PRAGMA foreign_key_check"))
        if violations:
            raise RuntimeError(f"Synthetic data contains foreign-key violations: {violations}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "retail.sqlite",
        help="database file to create (default: data/retail.sqlite)",
    )
    args = parser.parse_args()
    output = build_database(args.output.resolve())
    print(f"Created synthetic retail database: {output}")


if __name__ == "__main__":
    main()
