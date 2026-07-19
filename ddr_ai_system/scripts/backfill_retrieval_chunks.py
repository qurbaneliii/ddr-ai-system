from __future__ import annotations

import json

from ddr_ai.config import get_settings
from ddr_ai.db.session import session_scope, upgrade_schema
from ddr_ai.retrieval.corpus import backfill_retrieval_chunks


def main() -> None:
    settings = get_settings()
    upgrade_schema(settings.database_url)
    with session_scope(settings.database_url) as session:
        result = backfill_retrieval_chunks(session)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
