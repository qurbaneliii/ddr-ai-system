from __future__ import annotations

import argparse
import json

from ddr_ai.config import PROJECT_ROOT, get_settings
from ddr_ai.db.seeding import seed_database


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Idempotently import the committed demo dataset into an empty production database."
    )
    parser.add_argument("--confirm-empty-target", action="store_true")
    parser.add_argument("--seed-version", default="ddr-corpus-v1")
    args = parser.parse_args()
    if not args.confirm_empty_target:
        raise SystemExit("Pass --confirm-empty-target after verifying the target is correct.")
    settings = get_settings()
    if not settings.is_postgres:
        raise SystemExit("DDR_DATABASE_URL must reference PostgreSQL for production seeding.")
    source = f"sqlite:///{(PROJECT_ROOT / 'data/processed/ddr_ai.db').as_posix()}"
    result = seed_database(source, settings.database_url, seed_version=args.seed_version)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
