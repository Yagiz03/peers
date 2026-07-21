"""TEFAS (tefas.gov.tr) data-fetching layer.

TEFAS does not publish an authenticated public API, but the fund-data page
at tefas.gov.tr/tr/fon-verileri is backed by two JSON POST endpoints that
the site's own frontend calls:

- fonGnlBlgSiraliGetir: daily price / size / investor-count per fund.
- dagilimSiraliGetirT: daily asset-allocation breakdown per fund.

Both take a JSON body and return ``{"resultList": [...]}``. No auth
required. TEFAS caps a single request at ~1 month of history, so longer
ranges are split into 28-day chunks and concatenated.

Note: TEFAS previously exposed a legacy `/api/DB/BindHistoryInfo` endpoint
(still referenced in older blog posts/scrapers); that endpoint now 404s.
This module targets the endpoints currently in use.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

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


def _post(url: str, body: dict, field_map: dict, timeout: int = REQUEST_TIMEOUT) -> pd.DataFrame:
    resp = requests.post(url, json=body, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()

    err_msg = payload.get("errorMessage") or payload.get("errorCode")
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
