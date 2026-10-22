"""Seed the database with synthetic data: python -m blockport.ingestion.seed --days 90 --seed 42"""
from __future__ import annotations

import argparse

from ..db import init_db, make_engine, session_scope
from .synthetic import seed_database


def main() -> None:
    p = argparse.ArgumentParser(description="Seed synthetic BlockPort data")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--db", default=None, help="SQLAlchemy URL (default from config)")
    args = p.parse_args()
    engine = make_engine(args.db)
    init_db(engine)
    with session_scope(engine) as s:
        print(seed_database(s, days=args.days, seed=args.seed))


if __name__ == "__main__":
    main()
