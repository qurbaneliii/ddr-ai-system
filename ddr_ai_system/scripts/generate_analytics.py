from __future__ import annotations

import json

from ddr_ai.analytics.candidates import materialize_operational_candidates
from ddr_ai.config import get_settings
from ddr_ai.db.session import session_scope


def main() -> None:
    settings = get_settings()
    with session_scope(settings.database_url) as session:
        created = materialize_operational_candidates(session)
    print(json.dumps({"created": created, "total_created": sum(created.values())}, indent=2))


if __name__ == "__main__":
    main()
