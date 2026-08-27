"""Pre-fetch TEFAS's daily/YTD data once and save it to data/*.

TEFAS's own prices only update once a day (typically in the evening, after
markets close) - they do not change intraday. Having every visitor's page
load call TEFAS live is pure waste and is what was tripping the rate limit
in the first place. Instead, a scheduled GitHub Actions run (see
.github/workflows/data-refresh.yml, ~every 30 minutes between 08:00 and
10:00 Turkey time - comfortably covering whenever that day's update lands)
runs this script, commits the resulting files, and pushes. app.py reads
those files directly instead of calling tefas_client on every request; it
only falls back to a live call if a file is missing.

Per-fund detail pages (opened rarely, one fund at a time via the DETAY
link) still fetch live - there's no meaningful volume to pre-fetch there,
and the whole point is avoiding needless *repeated* calls for content that
every visitor sees.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import tefas_client as tf

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Every fund_type actually used by a configured PeerGroup (see config.py).
# Hardcoded rather than imported from config to keep this script runnable
# even if config.py picks up a new fund_type later without needing a
# matching edit here to go unnoticed - review config.py's PeerGroup
# fund_type values when adding a new one.
FUND_TYPES = ["YAT", "EMK"]


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    as_of = tf.last_business_day()
    start = as_of - timedelta(days=10)

    counts = {}
    for ftype in FUND_TYPES:
        universe = tf.fetch_universe_history(start, as_of, ftype)
        universe.to_csv(DATA_DIR / f"universe_{ftype}.csv", index=False)

        returns = tf.fetch_all_fund_returns(ftype)
        returns.to_json(DATA_DIR / f"returns_{ftype}.json", orient="records")

        fees = tf.fetch_management_fees(ftype)
        fees.to_json(DATA_DIR / f"fees_{ftype}.json", orient="records")

        counts[ftype] = {
            "universe_rows": len(universe),
            "returns_rows": len(returns),
            "fees_rows": len(fees),
        }
        print(f"{ftype}: {counts[ftype]}")

    meta = {
        "as_of": as_of.isoformat(),
        "fetched_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "counts": counts,
    }
    (DATA_DIR / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    print("meta:", meta)


if __name__ == "__main__":
    main()
