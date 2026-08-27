"""TEFAS Fon Takip - Streamlit clone.

Renders data for a configurable set of "peer groups" (config.py) the way
the original ykpfontakip.streamlit.app does: a daily-return table, a
date-range-return table, a YTD table per group, and a per-fund detail page
(opened via the DETAY link in the daily table).

The daily/YTD tables read from data/*.csv|json - a snapshot refreshed a
few times each morning by .github/workflows/data-refresh.yml, since
TEFAS's own prices only change once a day. That's a deliberate choice:
every visitor's page load used to call tefas.gov.tr live, which tripped
its per-IP rate limit past a handful of concurrent groups. Falls back to
a live tefas_client call only when the snapshot file is missing (e.g. the
very first deploy, before data-refresh has run once). The per-fund detail
page and the date-range table stay live - they're opened rarely enough,
one fund/range at a time, that pre-fetching them would be wasted work.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from config import CATEGORIES, PeerGroup, find_fund_type, find_group
import tefas_client as tf

st.set_page_config(page_title="TEFAS Fon Getirileri", page_icon="📈", layout="wide")

# Tighter paddings/font sizes on narrow (phone) viewports - Streamlit's
# defaults leave a lot of side margin and large headers that push tables
# off-screen on a phone, forcing horizontal scrolling for every row.
st.markdown(
    """
    <style>
    @media (max-width: 640px) {
        .block-container { padding: 3.5rem 0.5rem 2rem 0.5rem; }
        h1 { font-size: 1.3rem !important; }
        h3, h4 { font-size: 1.05rem !important; }
        [data-testid="stMetricValue"] { font-size: 1.05rem; }
        [data-testid="stMetricLabel"] { font-size: 0.75rem; }
        [data-testid="stDataFrame"] { font-size: 0.85rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

CACHE_TTL = 30 * 60  # 30 minutes

# TEFAS's own prices only change once a day (typically evening); a
# scheduled GitHub Actions run (.github/workflows/data-refresh.yml) fetches
# the day's data every 30 minutes from 08:00-10:00 Turkey time and commits
# it here, so the app can read it directly instead of every visitor's page
# load calling TEFAS live - which is what was tripping the rate limit.
DATA_DIR = Path(__file__).resolve().parent / "data"


# --------------------------------------------------------------------------
# Data access (cached)
# --------------------------------------------------------------------------

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _snapshot_meta() -> dict:
    path = DATA_DIR / "meta.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _snapshot_universe(fund_type: str) -> pd.DataFrame:
    path = DATA_DIR / f"universe_{fund_type}.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, parse_dates=["TARIH"])
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _snapshot_json(name: str) -> pd.DataFrame:
    path = DATA_DIR / name
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_json(path, orient="records")
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _allocation(fund_code: str, on: date, fund_type: str, lookback_days: int = 10) -> pd.DataFrame:
    try:
        return tf.fetch_fund_allocation(fund_code, on, fund_type, lookback_days=lookback_days)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _universe_history_live(start: date, end: date, fund_type: str) -> pd.DataFrame:
    try:
        return tf.fetch_universe_history(start, end, fund_type)
    except Exception:
        return pd.DataFrame()


def _universe_history(start: date, end: date, fund_type: str) -> pd.DataFrame:
    # Prefer the pre-fetched snapshot (covers the last 10 days as of its own
    # refresh) over a live call - it already covers the daily table's usual
    # window regardless of the exact start/end asked for here.
    snap = _snapshot_universe(fund_type)
    if not snap.empty:
        return snap
    return _universe_history_live(start, end, fund_type)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _fund_flow_history(fund_code: str, as_of: date, fund_type: str) -> pd.DataFrame:
    try:
        return tf.fetch_fund_flow_history(fund_code, as_of, fund_type)
    except Exception:
        return pd.DataFrame()


def _all_returns(fund_type: str) -> pd.DataFrame:
    snap = _snapshot_json(f"returns_{fund_type}.json")
    if not snap.empty:
        return snap
    return _all_returns_live(fund_type)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _all_returns_live(fund_type: str) -> pd.DataFrame:
    try:
        return tf.fetch_all_fund_returns(fund_type)
    except Exception:
        return pd.DataFrame()


def _management_fees(fund_type: str) -> pd.DataFrame:
    snap = _snapshot_json(f"fees_{fund_type}.json")
    if not snap.empty:
        return snap
    return _management_fees_live(fund_type)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _management_fees_live(fund_type: str) -> pd.DataFrame:
    try:
        return tf.fetch_management_fees(fund_type)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _fund_profile(fund_code: str) -> dict:
    try:
        return tf.fetch_fund_profile(fund_code)
    except Exception:
        return {}


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _rank_change() -> dict:
    # {group_name: {fund_code: delta}}, delta > 0 = moved up since the
    # previous day. Written by scripts/refresh_data.py from its own
    # snapshots - TEFAS's public API has no rank/rank-change field.
    path = DATA_DIR / "rank_change.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _fund_bilgi(fund_code: str) -> dict:
    try:
        return tf.fetch_fund_bilgi(fund_code)
    except Exception:
        return {}


# --------------------------------------------------------------------------
# Table builders
# --------------------------------------------------------------------------

def daily_table(group: PeerGroup, as_of: date) -> pd.DataFrame:
    # One request for the whole fund-type universe instead of one per fund -
    # TEFAS rate-limits per IP after a handful of requests, so a 13-fund
    # group like "Exotic Peers" would otherwise come back all N/A past the
    # first few funds.
    start = as_of - timedelta(days=10)
    universe = _universe_history(start, as_of, group.fund_type)
    rows = []
    for code in group.funds:
        hist = universe[universe["FONKODU"] == code] if not universe.empty else pd.DataFrame()
        daily_return, size, name = tf.compute_daily_return(hist)
        rows.append(
            {
                "FON KODU": code,
                "FON ADI": name or "N/A",
                "BÜYÜKLÜK": size,
                "GÜNLÜK GETİRİ": daily_return,
                "DETAY": f"?code={code}",
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("GÜNLÜK GETİRİ", ascending=False, na_position="last").reset_index(drop=True)
    return df


def range_table(group: PeerGroup, start: date, end: date) -> pd.DataFrame:
    universe = _universe_history(start, end, group.fund_type)
    rows = []
    for code in group.funds:
        hist = universe[universe["FONKODU"] == code] if not universe.empty else pd.DataFrame()
        ret = tf.compute_range_return(hist)
        name = hist.iloc[-1]["FONUNVAN"] if not hist.empty else "N/A"
        rows.append({"FON KODU": code, "FON ADI": name, "GETİRİ": ret})
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("GETİRİ", ascending=False, na_position="last").reset_index(drop=True)
    return df


def ytd_table(group: PeerGroup, as_of: date, size_by_code: dict) -> pd.DataFrame:
    # One request for all funds of this type instead of one per fund - TEFAS
    # rate-limits aggressively, and fonGetiriBazliBilgiGetir already returns
    # YTD (and other period) returns plus risk value for every fund at once.
    returns_df = _all_returns(group.fund_type)
    fees_df = _management_fees(group.fund_type)
    rank_change = _rank_change().get(group.name, {})

    returns_by_code = {}
    if not returns_df.empty and "fonKodu" in returns_df.columns:
        returns_by_code = {r["fonKodu"]: r for r in returns_df.to_dict("records")}
    fees_by_code = {}
    if not fees_df.empty and "fonKodu" in fees_df.columns:
        fees_by_code = {r["fonKodu"]: r for r in fees_df.to_dict("records")}

    rows = []
    for code in group.funds:
        r = returns_by_code.get(code, {})
        fee = fees_by_code.get(code, {})
        applied_fee = tf.parse_turkish_decimal(fee.get("uygulananYu1Y")) if fee else None
        rows.append(
            {
                "FON KODU": code,
                "FON ADI": r.get("fonUnvan", "N/A"),
                "YÖN. ÜCRETİ": applied_fee,
                "BÜYÜKLÜK": size_by_code.get(code),
                "YTD GETİRİ": r.get("getiriyb"),
                "SIRA DEĞ.": rank_change.get(code),
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("YTD GETİRİ", ascending=False, na_position="last").reset_index(drop=True)
    return df


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------

def fmt_pct(v) -> str:
    if v is None or pd.isna(v):
        return "N/A"
    return f"{v:,.4f}%".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_size(v) -> str:
    if v is None or pd.isna(v):
        return "N/A"
    return f"{v:,.0f} TL".replace(",", ".")


def fmt_price(v) -> str:
    if v is None or pd.isna(v):
        return "N/A"
    return f"{v:,.6f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_rank_change(v) -> str:
    if v is None or pd.isna(v) or v == 0:
        return "-"
    v = int(v)
    return f"▲{v}" if v > 0 else f"▼{-v}"


# --------------------------------------------------------------------------
# Per-fund detail page (opened via the DETAY link in the daily table)
# --------------------------------------------------------------------------

def render_fund_detail(code: str) -> None:
    code = code.upper()
    fund_type = find_fund_type(code)
    as_of = tf.last_business_day()

    if st.button("← Listeye dön"):
        st.query_params.clear()
        st.rerun()

    st.markdown(
        f"<h1 style='text-align:center;color:#4da3ff;'>{code} - Fon Detayları</h1>",
        unsafe_allow_html=True,
    )

    with st.spinner("TEFAS'tan veri çekiliyor..."):
        hist = _fund_flow_history(code, as_of, fund_type)
        fees_df = _management_fees(fund_type)
        returns_df = _all_returns(fund_type)
        profile = _fund_profile(code)
        bilgi = _fund_bilgi(code)
        # TEFAS's allocation endpoint rejects windows wider than ~1 month
        # ("Tarih aralığı 1 ayı aşamaz"); 27 days stays safely under that.
        alloc = _allocation(code, as_of, fund_type, lookback_days=27)

    if hist.empty:
        st.warning(f"'{code}' için veri bulunamadı.")
        return

    name = hist.iloc[-1].get("FONUNVAN") or code
    son_fiyat = hist.iloc[-1].get("FIYAT")
    fon_buyuklugu = hist.iloc[-1].get("PORTFOYBUYUKLUK")
    st.subheader(name)

    last_idx = len(hist) - 1
    gunluk_idx = last_idx - 1 if last_idx >= 1 else None
    haftalik_idx = tf.find_row_on_or_before(hist, as_of - timedelta(days=7))
    if haftalik_idx is not None and haftalik_idx >= last_idx:
        haftalik_idx = None
    month_start = pd.Timestamp(date(as_of.year, as_of.month, 1))
    this_month = hist[hist["TARIH"] >= month_start]
    ay_basi_idx = int(this_month.index[0]) if not this_month.empty and this_month.index[0] < last_idx else None
    yil_basi_idx = 0 if last_idx >= 1 else None

    def flow(idx):
        return fmt_size(tf.compute_net_flow(hist, idx)) if idx is not None else "N/A"

    fee_row = {}
    if not fees_df.empty and "fonKodu" in fees_df.columns:
        match = fees_df[fees_df["fonKodu"] == code]
        if not match.empty:
            fee_row = match.iloc[0].to_dict()
    applied_fee = tf.parse_turkish_decimal(fee_row.get("uygulananYu1Y")) if fee_row else None

    st.markdown("#### Net Giriş Çıkış")
    with st.container(border=True):
        c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
        c1.metric("Son Fiyat", fmt_price(son_fiyat))
        c2.metric("Günlük Net Giriş", flow(gunluk_idx))
        c3.metric("Haftalık Giriş", flow(haftalik_idx))
        c4.metric("Ay Başından Net Giriş", flow(ay_basi_idx))
        c5.metric("Yılbaşından İtibaren Net Giriş", flow(yil_basi_idx))
        c6.metric("Fon Büyüklüğü", fmt_size(fon_buyuklugu))
        c7.metric(
            "Fon Yıllık Yönetim Ücreti",
            f"%{applied_fee:.2f}".replace(".", ",") if applied_fee is not None else "-",
        )

    returns_row = {}
    if not returns_df.empty and "fonKodu" in returns_df.columns:
        match = returns_df[returns_df["fonKodu"] == code]
        if not match.empty:
            returns_row = match.iloc[0].to_dict()

    if returns_row or profile or bilgi:
        st.markdown("#### Fon Bilgileri")
        with st.container(border=True):
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("Kategori", bilgi.get("fonKategori") or returns_row.get("fonTurAciklama") or "-")
            risk = profile.get("riskDegeri") or returns_row.get("riskDegeri")
            d2.metric("Risk Değeri", str(risk) if risk else "-")
            d3.metric("ISIN", profile.get("isinKodu") or "-")
            if bilgi.get("kategoriDerece") and bilgi.get("kategoriFonSay"):
                d4.metric("Kategori Sırası", f"{bilgi['kategoriDerece']} / {bilgi['kategoriFonSay']}")
            else:
                d4.metric("Kategori Sırası", "-")

            e1, e2, e3, e4, e5 = st.columns(5)
            e1.metric("1A Getiri", fmt_pct(returns_row.get("getiri1a")))
            e2.metric("3A Getiri", fmt_pct(returns_row.get("getiri3a")))
            e3.metric("6A Getiri", fmt_pct(returns_row.get("getiri6a")))
            e4.metric("YTD Getiri", fmt_pct(returns_row.get("getiriyb")))
            e5.metric("1Y Getiri", fmt_pct(returns_row.get("getiri1y")))

            if profile.get("girisKomisyonu") or profile.get("cikisKomisyonu") or profile.get("kapLink"):
                f1, f2 = st.columns(2)
                f1.write(f"**Giriş Komisyonu:** {profile.get('girisKomisyonu') or '-'}")
                f2.write(f"**Çıkış Komisyonu:** {profile.get('cikisKomisyonu') or '-'}")
                if profile.get("kapLink"):
                    st.markdown(f"[KAP sayfası]({profile['kapLink']})")

    st.markdown(f"#### {code} Varlık Dağılımı")
    st.caption("Son 30 gün değişimleri")
    if alloc.empty:
        st.info("Varlık dağılımı verisi bulunamadı.")
    else:
        numeric_cols = [
            c for c in alloc.columns
            if c not in ("TARIH", "FONKODU") and pd.api.types.is_numeric_dtype(alloc[c])
        ]
        nonzero_cols = [c for c in numeric_cols if (alloc[c].fillna(0) != 0).any()]
        if not nonzero_cols:
            st.info("Varlık dağılımı verisi bulunamadı.")
        else:
            disp = alloc[["TARIH"] + nonzero_cols].copy()
            disp = disp.sort_values("TARIH", ascending=False)
            disp["TARIH"] = disp["TARIH"].dt.strftime("%d.%m.%Y")
            st.dataframe(disp, use_container_width=True, hide_index=True)


# --------------------------------------------------------------------------
# Route: a "DETAY" link sets ?code=XXX in a new tab - render that fund's
# detail page instead of the peer-group listing.
# --------------------------------------------------------------------------

query_code = st.query_params.get("code")
if query_code:
    render_fund_detail(query_code)
    st.stop()


# --------------------------------------------------------------------------
# Sidebar navigation
# --------------------------------------------------------------------------

st.sidebar.title("Getiri Analizi")

if "selected_group" not in st.session_state:
    st.session_state.selected_group = "YAK-YSU Peers"

for category in CATEGORIES:
    with st.sidebar.expander(category.name, expanded=False):
        for group in category.groups:
            is_selected = st.session_state.selected_group == group.name
            if st.button(group.name, key=f"nav_{group.name}", use_container_width=True, type="primary" if is_selected else "secondary"):
                st.session_state.selected_group = group.name
                st.rerun()

group = find_group(st.session_state.selected_group)

# --------------------------------------------------------------------------
# Main content
# --------------------------------------------------------------------------

st.markdown(
    "<h1 style='text-align:center;color:#4da3ff;'>TEFAS Fon Takip</h1>"
    "<p style='text-align:center;color:#9aa4b2;'>Fon Performansları</p>",
    unsafe_allow_html=True,
)

if group is None:
    st.error("Grup bulunamadı.")
    st.stop()

if not group.funds:
    st.info(
        f"**{group.name}** için henüz fon kodu tanımlanmadı. "
        "Fon kodlarını `config.py` içindeki ilgili `PeerGroup` tanımına ekleyin; "
        "tablolar otomatik olarak dolacaktır."
    )
    st.stop()

as_of = tf.last_business_day()

meta = _snapshot_meta()
if meta.get("fetched_at_utc"):
    st.caption(f"Veri kaynağı: günlük önbellek (son güncelleme: {meta['fetched_at_utc']} UTC)")

st.subheader(f"{group.name} - Günlük")

with st.spinner("TEFAS'tan veri çekiliyor..."):
    daily_df = daily_table(group, as_of)

if daily_df.empty:
    st.warning("Veri alınamadı. TEFAS servisine ulaşılamıyor olabilir.")
else:
    display_df = daily_df.copy()
    display_df["BÜYÜKLÜK"] = display_df["BÜYÜKLÜK"].map(fmt_size)
    display_df["GÜNLÜK GETİRİ"] = daily_df["GÜNLÜK GETİRİ"].map(fmt_pct)
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "FON KODU": st.column_config.TextColumn("FON KODU", width="small"),
            "FON ADI": st.column_config.TextColumn("FON ADI", width="small"),
            "BÜYÜKLÜK": st.column_config.TextColumn("BÜYÜKLÜK", width="small"),
            "GÜNLÜK GETİRİ": st.column_config.TextColumn("GÜNLÜK GETİRİ", width="small"),
            "DETAY": st.column_config.LinkColumn("DETAY", display_text="DETAY", width="small"),
        },
    )

st.divider()

st.subheader(f"{group.name} - Tarih Aralığı Getirileri")
with st.expander("Tarih Aralığı Seç"):
    default_start = as_of - timedelta(days=30)
    c1, c2 = st.columns(2)
    range_start = c1.date_input("Başlangıç", value=default_start, max_value=as_of, key="range_start")
    range_end = c2.date_input("Bitiş", value=as_of, max_value=as_of, key="range_end")
    if range_start >= range_end:
        st.error("Başlangıç tarihi bitiş tarihinden önce olmalı.")
    # Only fetch on explicit request - an expander's body runs on every
    # rerun even while collapsed, so computing this unconditionally meant a
    # default 30-day span (2 request chunks) fired on every single page
    # visit, whether or not anyone opened this section.
    elif st.button("Getiriyi Hesapla", key="range_calc_btn"):
        st.session_state["range_result"] = (
            (group.name, range_start, range_end),
            range_table(group, range_start, range_end),
        )

    cached_range = st.session_state.get("range_result")
    if cached_range and cached_range[0] == (group.name, range_start, range_end):
        rdf = cached_range[1]
        if rdf.empty:
            st.warning("Veri alınamadı.")
        else:
            rdisp = rdf.copy()
            rdisp["GETİRİ"] = rdf["GETİRİ"].map(fmt_pct)
            st.dataframe(rdisp, use_container_width=True, hide_index=True)
    elif range_start < range_end:
        st.caption("Hesaplamak için tarih aralığı seçip **Getiriyi Hesapla**'ya tıklayın.")

st.divider()

st.subheader(f"{group.name} - YTD")
size_by_code = (
    dict(zip(daily_df["FON KODU"], daily_df["BÜYÜKLÜK"])) if not daily_df.empty else {}
)
with st.spinner("YTD hesaplanıyor..."):
    ydf = ytd_table(group, as_of, size_by_code)
if ydf.empty:
    st.warning("Veri alınamadı.")
else:
    ydisp = ydf.copy()
    ydisp["BÜYÜKLÜK"] = ydf["BÜYÜKLÜK"].map(fmt_size)
    ydisp["YTD GETİRİ"] = ydf["YTD GETİRİ"].map(fmt_pct)
    ydisp["YÖN. ÜCRETİ"] = ydf["YÖN. ÜCRETİ"].map(
        lambda v: "-" if v is None or pd.isna(v) else f"%{v:.2f}".replace(".", ",")
    )
    ydisp["SIRA DEĞ."] = ydf["SIRA DEĞ."].map(fmt_rank_change)
    st.dataframe(
        ydisp[["FON KODU", "FON ADI", "YÖN. ÜCRETİ", "BÜYÜKLÜK", "YTD GETİRİ", "SIRA DEĞ."]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "FON KODU": st.column_config.TextColumn("FON KODU", width="small"),
            "FON ADI": st.column_config.TextColumn("FON ADI", width="small"),
            "YÖN. ÜCRETİ": st.column_config.TextColumn("YÖN. ÜCRETİ", width="small"),
            "BÜYÜKLÜK": st.column_config.TextColumn("BÜYÜKLÜK", width="small"),
            "YTD GETİRİ": st.column_config.TextColumn("YTD GETİRİ", width="small"),
            "SIRA DEĞ.": st.column_config.TextColumn("SIRA DEĞ.", width="small"),
        },
    )

st.caption(
    "Veriler tefas.gov.tr üzerinden çekilmektedir (fonGnlBlgSiraliGetir, "
    "dagilimSiraliGetirT, fonGetiriBazliBilgiGetir, fonYonetimBazliBilgiGetir, "
    "fonProfilBilgiGetir, fonBilgiGetir uçları). Brüt getiri ve sıra değişimi "
    "gibi bazı alanlar TEFAS'ın herkese açık servislerinde yer almadığı için "
    "gösterilmemektedir."
)
