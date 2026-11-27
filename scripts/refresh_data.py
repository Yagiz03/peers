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
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import config
import tefas_client as tf

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Every fund type TEFAS's own "Fon Verileri" menu exposes: Menkul Kıymet
# Yatırım Fonları (YAT), Emeklilik Fonları (EMK), Borsa Yatırım Fonları
# (BYF), Gayrimenkul Yatırım Fonları (GYF), Girişim Sermayesi Yatırım
# Fonları (GSYF). Only YAT and EMK are used by a configured PeerGroup today
# (see config.py), but pre-fetching all five now means the other three are
# already cached and ready whenever a peer group needs them, instead of
# waiting on a live TEFAS call the first time someone adds one.
FUND_TYPES = ["YAT", "EMK", "BYF", "GYF", "GSYF"]

RANK_HISTORY_PATH_NAME = "rank_history.json"
RANK_CHANGE_PATH_NAME = "rank_change.json"


def _group_ranks(returns_by_type: dict) -> dict:
    """YTD-return rank (1 = best) per configured peer group, keyed by
    group name then fund code. Computed from this run's own
    fonGetiriBazliBilgiGetir data - TEFAS's public API has no rank/rank-
    change field, but the rank itself is just a sort we can do ourselves."""
    ranks: dict[str, dict[str, int]] = {}
    for category in config.CATEGORIES:
        for group in category.groups:
            if not group.funds:
                continue
            returns_df = returns_by_type.get(group.fund_type)
            if returns_df is None or returns_df.empty or "fonKodu" not in returns_df.columns:
                continue
            sub = returns_df[returns_df["fonKodu"].isin(group.funds)]
            sub = sub.sort_values("getiriyb", ascending=False, na_position="last")
            ranks[group.name] = {code: i + 1 for i, code in enumerate(sub["fonKodu"])}
    return ranks


def _update_rank_change(today_str: str, today_ranks: dict) -> None:
    """Diff today's per-group rank against the last *different calendar
    day's* stored rank (not the last run - this job may run more than once
    a day (manual runs), and a rank "change" should mean day-over-day, not
    run-over-run). Writes rank_change.json: {group: {code: delta}} where
    delta > 0 means the fund moved up (better) since the previous day."""
    history_path = DATA_DIR / RANK_HISTORY_PATH_NAME
    history = json.loads(history_path.read_text()) if history_path.exists() else {}

    if history.get("date") == today_str:
        prev_ranks = history.get("prev_ranks", {})
    else:
        prev_ranks = history.get("ranks", {})

    rank_change = {}
    for gname, ranks in today_ranks.items():
        prev_g = prev_ranks.get(gname, {})
        rank_change[gname] = {
            code: prev_g[code] - r for code, r in ranks.items() if code in prev_g
        }
    (DATA_DIR / RANK_CHANGE_PATH_NAME).write_text(json.dumps(rank_change, ensure_ascii=False))

    history_path.write_text(
        json.dumps({"date": today_str, "ranks": today_ranks, "prev_ranks": prev_ranks}, ensure_ascii=False)
    )


MAX_ATTEMPTS = 4
RETRY_WAIT_SECONDS = 90


def main() -> None:
    """Run _refresh() with retries. A scheduled run used to be repeated every
    30 minutes to paper over transient TEFAS errors (429s, resets); retrying
    here instead costs ~minutes, not whole extra workflow runs. A failure
    after the last attempt exits non-zero so the workflow commits nothing."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            _refresh()
            return
        except Exception as exc:  # noqa: BLE001 - any TEFAS/network/parse failure
            print(f"attempt {attempt}/{MAX_ATTEMPTS} failed: {exc!r}", file=sys.stderr)
            if attempt == MAX_ATTEMPTS:
                raise
            time.sleep(RETRY_WAIT_SECONDS * attempt)


def _refresh() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    as_of = tf.last_business_day()
    start = as_of - timedelta(days=10)

    counts = {}
    returns_by_type = {}
    for ftype in FUND_TYPES:
        universe = tf.fetch_universe_history(start, as_of, ftype)
        universe.to_csv(DATA_DIR / f"universe_{ftype}.csv", index=False)

        returns = tf.fetch_all_fund_returns(ftype)
        returns.to_json(DATA_DIR / f"returns_{ftype}.json", orient="records")
        returns_by_type[ftype] = returns

        fees = tf.fetch_management_fees(ftype)
        fees.to_json(DATA_DIR / f"fees_{ftype}.json", orient="records")

        counts[ftype] = {
            "universe_rows": len(universe),
            "returns_rows": len(returns),
            "fees_rows": len(fees),
        }
        print(f"{ftype}: {counts[ftype]}")

    _update_rank_change(as_of.isoformat(), _group_ranks(returns_by_type))

    meta = {
        "as_of": as_of.isoformat(),
        "fetched_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "counts": counts,
    }
    (DATA_DIR / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    print("meta:", meta)


if __name__ == "__main__":
    main()
