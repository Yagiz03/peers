"""TEFAS (tefas.gov.tr) unofficial data-fetching layer.

TEFAS does not publish a public API, but the "Tarihsel Veriler" (historical
data) page on tefas.gov.tr is backed by two JSON endpoints that the site's
own JavaScript calls. We use the same endpoints here:

- BindHistoryInfo: daily price / size / investor-count per fund, for a date
  range.
- BindHistoryAllocation: daily asset-allocation breakdown per fund.

Both are POST endpoints that take Turkish-locale form fields and return
``{"data": [...]}``. Nothing here requires authentication.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import requests

BASE_URL = "https://www.tefas.gov.tr"
INFO_ENDPOINT = f"{BASE_URL}/api/DB/BindHistoryInfo"
ALLOCATION_ENDPOINT = f"{BASE_URL}/api/DB/BindHistoryAllocation"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/TarihselVeriler.aspx",
    "X-Requested-With": "XMLHttpRequest",
}

REQUEST_TIMEOUT = 20


def _tr_date(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def _post(endpoint: str, payload: dict, timeout: int = REQUEST_TIMEOUT) -> list[dict]:
    resp = requests.post(endpoint, data=payload, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    return body.get("data", [])


def fetch_fund_history(
    fund_code: str,
    start: date,
    end: date,
    fund_type: str = "YAT",
) -> pd.DataFrame:
    """Daily price/size history for a single fund between start and end.

    fund_type: "YAT" for regular (securities) mutual funds, "EMK" for
    pension (emeklilik) funds. Columns of interest in the response:
    TARIH (epoch ms), FONKODU, FONUNVAN, FIYAT, PORTFOYBUYUKLUK,
    TEDPAYSAYISI, KISISAYISI.
    """
    payload = {
        "fontip": fund_type,
        "sfontur": "",
        "fonkod": fund_code,
        "fongrup": "",
        "bastarih": _tr_date(start),
        "bittarih": _tr_date(end),
        "fonunvantip": "",
        "kurucukod": "",
    }
    rows = _post(INFO_ENDPOINT, payload)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["TARIH"] = pd.to_datetime(df["TARIH"], unit="ms")
    df = df.sort_values("TARIH").reset_index(drop=True)
    return df


def fetch_fund_allocation(
    fund_code: str,
    on: date,
    fund_type: str = "YAT",
    lookback_days: int = 10,
) -> pd.DataFrame:
    """Asset allocation breakdown for a fund, as of the most recent
    available date on or before ``on``. Columns vary by fund type (equity
    weight, bonds, precious metals, FX, ...) so callers should treat the
    result as a generic wide dataframe and pick numeric columns > 0.
    """
    payload = {
        "fontip": fund_type,
        "fonkod": fund_code,
        "bastarih": _tr_date(on - timedelta(days=lookback_days)),
        "bittarih": _tr_date(on),
    }
    rows = _post(ALLOCATION_ENDPOINT, payload)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["TARIH"] = pd.to_datetime(df["TARIH"], unit="ms")
    df = df.sort_values("TARIH").reset_index(drop=True)
    return df


def last_business_day(today: date | None = None) -> date:
    d = today or date.today()
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d -= timedelta(days=1)
    return d


def compute_daily_return(history: pd.DataFrame) -> tuple[float | None, float | None, str | None]:
    """Returns (daily_return_pct, latest_size, fund_name) from a history
    dataframe sorted ascending by date. daily_return_pct is None if fewer
    than 2 price points are available (e.g. newly listed fund or holiday).
    """
    if history is None or history.empty:
        return None, None, None
    name = history.iloc[-1].get("FONUNVAN")
    size = history.iloc[-1].get("PORTFOYBUYUKLUK")
    if len(history) < 2:
        return None, size, name
    prev_price = history.iloc[-2]["FIYAT"]
    last_price = history.iloc[-1]["FIYAT"]
    if not prev_price:
        return None, size, name
    daily_return = (last_price / prev_price - 1) * 100
    return daily_return, size, name


def compute_range_return(history: pd.DataFrame) -> float | None:
    """Total return between the first and last row of a history dataframe."""
    if history is None or history.empty or len(history) < 2:
        return None
    first_price = history.iloc[0]["FIYAT"]
    last_price = history.iloc[-1]["FIYAT"]
    if not first_price:
        return None
    return (last_price / first_price - 1) * 100
