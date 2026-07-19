from __future__ import annotations

from ddr_ai.config import get_settings
from ddr_ai.db.session import upgrade_schema
from ddr_ai.services.processor import process_paths


def main() -> None:
    settings = get_settings()
    upgrade_schema(settings.database_url)
    paths = sorted(settings.raw_dir.rglob("*.pdf"))
    for result in process_paths(paths, database_url=settings.database_url, settings=settings):
        print(result)


if __name__ == "__main__":
    main()
