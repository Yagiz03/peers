"""TEFAS (tefas.gov.tr) data-fetching layer.

TEFAS does not publish an authenticated public API, but the fund-data page
at tefas.gov.tr/tr/fon-verileri is backed by JSON POST endpoints that the
site's own frontend calls. All take a JSON body and return
``{"resultList": [...]}`` or ``{"errorMessage": ...}``; no auth required.

Two "legacy-shaped" endpoints (posted via ``_post``) take a date range and
optional fund code, and are used for price/allocation history:

- fonGnlBlgSiraliGetir (INFO_URL): daily price/size/investor-count per
  fund. Respects an empty fund code by returning the whole ~2000-fund
  universe for the date range (see ``fetch_universe_history``) - TEFAS
  caps a single request at ~1 month, so longer ranges are split into
  28-day chunks and concatenated.
- dagilimSiraliGetirT (DIST_URL): daily asset-allocation breakdown per
  fund. Same ~1-month cap, but ignores the fund-code filter and always
  returns every fund of that type - callers must filter client-side.

The rest (posted via ``_post_funds_api``) are newer ``/api/funds/*``
single-purpose endpoints with their own request shapes:

- fonGetiriBazliBilgiGetir: 1M/3M/6M/YTD/1Y/3Y/5Y returns + risk value for
  every fund of one type in one request.
- fonYonetimBazliBilgiGetir: management-fee data for every fund of one
  type in one request.
- fonProfilBilgiGetir / fonBilgiGetir: per-fund profile / core info.

Note: TEFAS previously exposed a legacy `/api/DB/BindHistoryInfo` endpoint
(still referenced in older blog posts/scrapers); that endpoint now 404s.
This module targets the endpoints currently in use, confirmed against
live responses.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import pandas as pd
import requests

BASE_URL = "https://www.tefas.gov.tr"
INFO_URL = f"{BASE_URL}/api/funds/fonGnlBlgSiraliGetir"
DIST_URL = f"{BASE_URL}/api/funds/dagilimSiraliGetirT"

HEADERS = {
    "Accept": "*/*",
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/tr/fon-verileri",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

REQUEST_TIMEOUT = 30
MAX_DAYS_PER_REQUEST = 28

# Raw TEFAS JSON key -> normalized column name
INFO_FIELDS = {
    "fonKodu": "FONKODU",
    "fonUnvan": "FONUNVAN",
    "tarih": "TARIH",
    "fiyat": "FIYAT",
    "tedPaySayisi": "TEDPAYSAYISI",
    "kisiSayisi": "KISISAYISI",
    "portfoyBuyukluk": "PORTFOYBUYUKLUK",
    "borsaBultenFiyat": "BORSABULTENFIYAT",
}

DIST_FIELDS = {
    "fonKodu": "FONKODU",
    "fonUnvan": "FONUNVAN",
    "tarih": "TARIH",
    "hs": "Hisse Senedi",
    "dt": "Devlet Tahvili",
    "hb": "Hazine Bonosu",
    "fb": "Finansman Bonosu",
    "ost": "Özel Sektör Tahvili",
    "bb": "Banka Bonosu",
    "vdm": "Varlığa Dayalı Menkul Kıymet",
    "eut": "Eurobond",
    "kibd": "Kamu Dış Borçlanma",
    "osdb": "Özel Sektör Dış Borçlanma",
    "kba": "Kira Sertifikası (Kamu, TL)",
    "r": "Repo",
    "tr": "Ters Repo",
    "vm": "Vadeli Mevduat",
    "vmtl": "Vadeli Mevduat (TL)",
    "vmd": "Vadeli Mevduat (Döviz)",
    "vmau": "Vadeli Mevduat (Altın)",
    "kh": "Katılma Hesabı",
    "kks": "Kira Sertifikası (Kamu)",
    "osks": "Kira Sertifikası (Özel Sektör)",
    "km": "Kıymetli Maden",
    "kmbyf": "Kıymetli Maden BYF",
    "ymk": "Yabancı Menkul Kıymet",
    "yhs": "Yabancı Hisse Senedi",
    "ybyf": "Yabancı BYF",
    "fkb": "Fon Katılma Belgesi",
    "yyf": "Yatırım Fonu",
    "byf": "Borsa Yatırım Fonu",
    "gykb": "Gayrimenkul YF Katılma Belgesi",
    "gsykb": "Girişim Sermayesi YF Katılma Belgesi",
    "t": "Türev Araçlar",
    "vint": "Vadeli İşlem Nakit Teminatı",
    "gas": "Gayrimenkul Sertifikası",
    "tpp": "Takasbank Para Piyasası",
    "bpp": "BIST Para Piyasası",
    "d": "Diğer",
}


def _parse_date_field(v) -> pd.Timestamp | None:
    if v is None:
        return None
    try:
        # numeric epoch milliseconds
        if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit() and len(v) >= 12):
            return pd.to_datetime(int(v), unit="ms")
        return pd.to_datetime(v)
    except (ValueError, TypeError):
        return None


def _post(
    url: str,
    body: dict,
    field_map: dict,
    timeout: int = REQUEST_TIMEOUT,
    max_retries: int = 2,
) -> pd.DataFrame:
    """POST to a legacy-shaped TEFAS endpoint (INFO_URL/DIST_URL) and parse
    its resultList. Retries once on a transient network error or 429 - since
    these endpoints are now used for whole-universe fetches shared by an
    entire peer group, a single unhandled failure here would blank out
    every fund in the group instead of just one."""
    payload = None
    for attempt in range(max_retries):
        if attempt > 0:
            time.sleep(2)
        try:
            resp = requests.post(url, json=body, headers=HEADERS, timeout=timeout)
            if resp.status_code == 429:
                continue
            resp.raise_for_status()
            payload = resp.json()
            break
        except (requests.exceptions.RequestException, ValueError):
            continue
    if payload is None:
        return pd.DataFrame()

    rows = payload.get("resultList") or []
    if not rows:
        return pd.DataFrame()

    records = []
    for row in rows:
        rec = {}
        for short, target in field_map.items():
            rec[target] = row.get(short)
        records.append(rec)

    df = pd.DataFrame(records)
    if "TARIH" in df.columns:
        df["TARIH"] = df["TARIH"].map(_parse_date_field)
    return df


def _build_body(fund_code: str | None, start: date, end: date, fund_type: str) -> dict:
    return {
        "fonTipi": fund_type,
        "fonKodu": fund_code,
        "aramaMetni": None,
        "fonTurKod": None,
        "fonGrubu": None,
        "sfonTurKod": None,
        "fonTurAciklama": None,
        "kurucuKod": None,
        "basTarih": start.strftime("%Y%m%d"),
        "bitTarih": end.strftime("%Y%m%d"),
        "basSira": 1,
        "bitSira": 100000,
        "dil": "TR",
        "sFonTurKod": "",
        "fonKod": "",
        "fonGrup": "",
        "fonUnvanTip": "",
    }


def _split_range(start: date, end: date, max_days: int = MAX_DAYS_PER_REQUEST) -> list[tuple[date, date]]:
    chunks = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=max_days - 1), end)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks


def fetch_fund_history(
    fund_code: str,
    start: date,
    end: date,
    fund_type: str = "YAT",
) -> pd.DataFrame:
    """Daily price/size history for a single fund between start and end
    (inclusive), sorted ascending by date."""
    frames = []
    for chunk_start, chunk_end in _split_range(start, end):
        body = _build_body(fund_code, chunk_start, chunk_end, fund_type)
        df = _post(INFO_URL, body, INFO_FIELDS)
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["TARIH"]).sort_values("TARIH").reset_index(drop=True)
    return out


def fetch_universe_history(
    start: date,
    end: date,
    fund_type: str = "YAT",
) -> pd.DataFrame:
    """Daily price/size history for every fund of one type between start and
    end (inclusive) - one request per 28-day chunk, regardless of how many
    funds the caller ultimately needs. Confirmed empirically: passing no
    fund code returns the whole ~2000-fund universe for the date range
    instead of erroring or returning nothing.

    Rendering a peer group by calling ``fetch_fund_history`` once per fund
    hits TEFAS's per-IP rate limit past a handful of funds (empirically
    ~4 requests before a 429/connection-reset); fetching the whole universe
    once and filtering client-side by FONKODU avoids that regardless of
    group size."""
    frames = []
    for chunk_start, chunk_end in _split_range(start, end):
        body = _build_body(None, chunk_start, chunk_end, fund_type)
        df = _post(INFO_URL, body, INFO_FIELDS)
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["TARIH"]).sort_values(["FONKODU", "TARIH"]).reset_index(drop=True)
    return out


def fetch_fund_allocation(
    fund_code: str,
    on: date,
    fund_type: str = "YAT",
    lookback_days: int = 10,
) -> pd.DataFrame:
    """Asset allocation breakdown for a fund, covering the window ending on
    ``on``. Non-FONKODU/FONUNVAN/TARIH columns are asset-weight percentages;
    callers should pick numeric columns > 0 from the most recent row."""
    start = on - timedelta(days=lookback_days)
    body = _build_body(fund_code, start, on, fund_type)
    df = _post(DIST_URL, body, DIST_FIELDS)
    if df.empty:
        return df
    # The distribution endpoint ignores the fonKodu filter and returns every
    # fund of this type for the date range, unlike the info endpoint - filter
    # client-side.
    df = df[df["FONKODU"] == fund_code]
    if df.empty:
        return df
    df = df.dropna(subset=["TARIH"]).sort_values("TARIH").reset_index(drop=True)
    return df


def parse_turkish_decimal(value) -> float | None:
    """Parse a Turkish-locale decimal string (comma separator), e.g. "2,2"."""
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except (ValueError, TypeError):
        return None


def _post_funds_api(
    endpoint: str,
    payload: dict,
    max_retries: int = 2,
    timeout: int = REQUEST_TIMEOUT,
) -> list[dict]:
    """POST to a TEFAS ``/api/funds/*`` endpoint and return its resultList.

    A short-lived retry (not the ~45s backoff some scrapers use, which would
    freeze the app) covers a transient 429; a persistent rate limit just
    yields an empty list so callers degrade to "-" instead of hanging.
    """
    url = f"{BASE_URL}/api/funds/{endpoint}"
    for attempt in range(max_retries):
        if attempt > 0:
            time.sleep(2)
        try:
            resp = requests.post(url, json=payload, headers=HEADERS, timeout=timeout)
            if resp.status_code == 429:
                continue
            resp.raise_for_status()
            data = resp.json()
        except (requests.exceptions.RequestException, ValueError):
            # Network hiccup, timeout, or non-JSON body - retry, then give up
            # quietly. TEFAS tends to stall/reset connections after several
            # requests in quick succession; a crash here shouldn't take down
            # a page that only needed this data as a supplement.
            continue
        if data.get("errorMessage"):
            return []
        return data.get("resultList") or []
    return []


def fetch_all_fund_returns(fund_type: str = "YAT") -> pd.DataFrame:
    """All funds of one type with 1A/3A/6A/YTD/1Y/3Y/5Y returns and risk
    value in a single request (``fonGetiriBazliBilgiGetir``). Filter the
    result client-side by fund code - this is far cheaper than one request
    per fund when rendering a whole peer group."""
    rows = _post_funds_api(
        "fonGetiriBazliBilgiGetir",
        {
            "fonTipi": fund_type,
            "dil": "TR",
            "calismaTipi": 2,
            "donemGetiri1a": "1",
            "donemGetiri3a": "1",
            "donemGetiri6a": "1",
            "donemGetiriyb": "1",
            "donemGetiri1y": "1",
            "donemGetiri3y": "1",
            "donemGetiri5y": "1",
        },
    )
    return pd.DataFrame(rows)


def fetch_management_fees(fund_type: str = "YAT") -> pd.DataFrame:
    """All funds of one type with management-fee data
    (``fonYonetimBazliBilgiGetir``): applied fee, prospectus fee, max
    expense ratio."""
    rows = _post_funds_api("fonYonetimBazliBilgiGetir", {"fonTipi": fund_type, "dil": "TR"})
    return pd.DataFrame(rows)


def fetch_fund_profile(fund_code: str) -> dict:
    """Per-fund profile (``fonProfilBilgiGetir``): ISIN, KAP link, trading
    hours/valor, entry/exit fees, TEFAS status. Empty dict if unavailable."""
    rows = _post_funds_api("fonProfilBilgiGetir", {"fonKodu": fund_code, "dil": "TR"})
    return rows[0] if rows else {}


def fetch_fund_bilgi(fund_code: str) -> dict:
    """Per-fund core info (``fonBilgiGetir``): name, price, size, investor
    count, category, category rank, market share. Empty dict if
    unavailable."""
    rows = _post_funds_api("fonBilgiGetir", {"fonKodu": fund_code})
    return rows[0] if rows else {}


def fetch_fund_flow_history(
    fund_code: str,
    as_of: date,
    fund_type: str = "YAT",
) -> pd.DataFrame:
    """Just enough single-fund history to compute daily/weekly/MTD/YTD net
    flows: the last ~10 days plus a few days around the start of the
    current month and the start of the year. Fetching the whole
    Jan-1-to-today range would take ~9 sequential 28-day-chunk requests
    just to get 3 anchor dates out of it - this targets those anchors
    directly, cutting a fund's detail-page load to at most 3 requests
    regardless of how late in the year it is."""
    windows = [(as_of - timedelta(days=10), as_of)]
    month_start = date(as_of.year, as_of.month, 1)
    if month_start < windows[0][0]:
        windows.append((month_start, month_start + timedelta(days=6)))
    year_start = date(as_of.year, 1, 1)
    if year_start < windows[-1][0]:
        windows.append((year_start, year_start + timedelta(days=6)))

    frames = []
    for start, end in windows:
        h = fetch_fund_history(fund_code, start, min(end, as_of), fund_type)
        if not h.empty:
            frames.append(h)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset=["TARIH"]).sort_values("TARIH").reset_index(drop=True)
    return out


def compute_net_flow(history: pd.DataFrame, since_row_idx: int) -> float | None:
    """Net subscription/redemption money between ``history.iloc[since_row_idx]``
    and the last row, valued at the last row's price: standard
    ``(units_now - units_then) * price_now`` - separates actual money flow
    from price appreciation, unlike a raw portfolio-size delta."""
    if history is None or history.empty or since_row_idx < 0 or since_row_idx >= len(history):
        return None
    last = history.iloc[-1]
    then = history.iloc[since_row_idx]
    units_now = last.get("TEDPAYSAYISI")
    units_then = then.get("TEDPAYSAYISI")
    price_now = last.get("FIYAT")
    if units_now is None or units_then is None or price_now is None:
        return None
    return (units_now - units_then) * price_now


def find_row_on_or_before(history: pd.DataFrame, on: date) -> int | None:
    """Index of the last row in an ascending-by-TARIH history whose date is
    <= ``on``, or None if every row is after it."""
    if history is None or history.empty:
        return None
    cutoff = pd.Timestamp(on)
    eligible = history.index[history["TARIH"] <= cutoff]
    if len(eligible) == 0:
        return None
    return int(eligible[-1])


def last_business_day(today: date | None = None) -> date:
    d = today or date.today()
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d -= timedelta(days=1)
    return d


def compute_daily_return(history: pd.DataFrame) -> tuple[float | None, float | None, str | None]:
    """Returns (daily_return_pct, latest_size, fund_name) from a history
    dataframe sorted ascending by date. daily_return_pct is None if fewer
    than 2 price points are available (e.g. newly listed fund or holiday)."""
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
