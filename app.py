"""TEFAS Fon Takip - Streamlit clone.

Fetches live data from tefas.gov.tr's historical-data JSON endpoints
(see tefas_client.py) for a configurable set of "peer groups" (config.py)
and renders them the way the original ykpfontakip.streamlit.app does:
a daily-return table, a date-range-return table and a YTD table per group.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from config import CATEGORIES, PeerGroup, find_group
import tefas_client as tf

st.set_page_config(page_title="TEFAS Fon Getirileri", page_icon="📈", layout="wide")

CACHE_TTL = 30 * 60  # 30 minutes


# --------------------------------------------------------------------------
# Data access (cached)
# --------------------------------------------------------------------------

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _allocation(fund_code: str, on: date, fund_type: str) -> pd.DataFrame:
    try:
        return tf.fetch_fund_allocation(fund_code, on, fund_type)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _universe_history(start: date, end: date, fund_type: str) -> pd.DataFrame:
    try:
        return tf.fetch_universe_history(start, end, fund_type)
    except Exception:
        return pd.DataFrame()


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


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _all_returns(fund_type: str) -> pd.DataFrame:
    try:
        return tf.fetch_all_fund_returns(fund_type)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _management_fees(fund_type: str) -> pd.DataFrame:
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
def _fund_bilgi(fund_code: str) -> dict:
    try:
        return tf.fetch_fund_bilgi(fund_code)
    except Exception:
        return {}


def ytd_table(group: PeerGroup, as_of: date, size_by_code: dict) -> pd.DataFrame:
    # One request for all funds of this type instead of one per fund - TEFAS
    # rate-limits aggressively, and fonGetiriBazliBilgiGetir already returns
    # YTD (and other period) returns plus risk value for every fund at once.
    returns_df = _all_returns(group.fund_type)
    fees_df = _management_fees(group.fund_type)

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
                "SIRA DEĞ.": None,
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


def style_return(df: pd.DataFrame, col: str):
    def _color(v):
        if v is None or pd.isna(v):
            return "color: gray"
        return "color: #2ecc71" if v >= 0 else "color: #e74c3c"

    return (
        df.style.map(_color, subset=[col])
        .format({col: fmt_pct}, subset=[col])
    )


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

header_col, toggle_col = st.columns([4, 1])
with header_col:
    st.subheader(f"{group.name} - Günlük")
with toggle_col:
    show_allocation_change = st.toggle("Varlık Dağılımı Değişim", value=False, key="alloc_toggle")

with st.spinner("TEFAS'tan veri çekiliyor..."):
    daily_df = daily_table(group, as_of)

if daily_df.empty:
    st.warning("Veri alınamadı. TEFAS servisine ulaşılamıyor olabilir.")
else:
    display_df = daily_df.copy()
    display_df["BÜYÜKLÜK"] = display_df["BÜYÜKLÜK"].map(fmt_size)
    display_df["GÜNLÜK GETİRİ"] = daily_df["GÜNLÜK GETİRİ"].map(fmt_pct)
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    st.caption("Varlık dağılımı ve detay için bir fon seçin.")
    picked = st.selectbox("Fon", options=group.funds, key="alloc_pick")

    with st.expander(f"{picked} - DETAY"):
        with st.spinner("Detay bilgisi çekiliyor..."):
            bilgi = _fund_bilgi(picked)
            profile = _fund_profile(picked)
            returns_row = {}
            all_returns_df = _all_returns(group.fund_type)
            if not all_returns_df.empty and "fonKodu" in all_returns_df.columns:
                match = all_returns_df[all_returns_df["fonKodu"] == picked]
                if not match.empty:
                    returns_row = match.iloc[0].to_dict()

        if not bilgi and not profile and not returns_row:
            st.info("Detay verisi bulunamadı.")
        else:
            d1, d2, d3 = st.columns(3)
            d1.metric("Kategori", bilgi.get("fonKategori") or "-")
            risk = profile.get("riskDegeri") or returns_row.get("riskDegeri")
            d2.metric("Risk Değeri", str(risk) if risk else "-")
            d3.metric("ISIN", profile.get("isinKodu") or "-")

            e1, e2, e3, e4 = st.columns(4)
            e1.metric("1A Getiri", fmt_pct(returns_row.get("getiri1a")))
            e2.metric("3A Getiri", fmt_pct(returns_row.get("getiri3a")))
            e3.metric("6A Getiri", fmt_pct(returns_row.get("getiri6a")))
            e4.metric("1Y Getiri", fmt_pct(returns_row.get("getiri1y")))

            f1, f2 = st.columns(2)
            f1.write(f"**Giriş Komisyonu:** {profile.get('girisKomisyonu', '-')}")
            f2.write(f"**Çıkış Komisyonu:** {profile.get('cikisKomisyonu', '-')}")
            if profile.get("kapLink"):
                st.markdown(f"[KAP sayfası]({profile['kapLink']})")

    if show_allocation_change:
        earlier = as_of - timedelta(days=30)
        alloc_hist = _allocation(picked, as_of, group.fund_type)
        alloc_prev = _allocation(picked, earlier, group.fund_type)
        if alloc_hist.empty:
            st.info("Varlık dağılımı verisi bulunamadı.")
        else:
            latest = alloc_hist.iloc[-1]
            baseline = alloc_prev.iloc[0] if not alloc_prev.empty else None
            numeric_cols = [
                c for c in alloc_hist.columns
                if c not in ("TARIH", "FONKODU") and pd.api.types.is_numeric_dtype(alloc_hist[c])
            ]
            rows = []
            for c in numeric_cols:
                cur = latest.get(c) or 0
                prev = baseline.get(c, 0) if baseline is not None else 0
                if cur or prev:
                    rows.append({"VARLIK": c, "GÜNCEL %": cur, "DEĞİŞİM (30g)": cur - prev})
            if rows:
                st.dataframe(pd.DataFrame(rows).sort_values("GÜNCEL %", ascending=False), hide_index=True, use_container_width=True)
            else:
                st.info("Varlık dağılımı verisi bulunamadı.")
    else:
        alloc = _allocation(picked, as_of, group.fund_type)
        if alloc.empty:
            st.info("Varlık dağılımı verisi bulunamadı.")
        else:
            latest = alloc.iloc[-1]
            numeric_cols = [
                c for c in alloc.columns
                if c not in ("TARIH", "FONKODU") and pd.api.types.is_numeric_dtype(alloc[c])
            ]
            weights = {c: latest[c] for c in numeric_cols if latest[c]}
            if weights:
                chart_df = pd.DataFrame({"VARLIK": list(weights.keys()), "ORAN (%)": list(weights.values())})
                chart_df = chart_df.sort_values("ORAN (%)", ascending=False)
                st.bar_chart(chart_df.set_index("VARLIK"))
            else:
                st.info("Varlık dağılımı verisi bulunamadı.")

st.divider()

st.subheader(f"{group.name} - Tarih Aralığı Getirileri")
with st.expander("Tarih Aralığı Seç"):
    default_start = as_of - timedelta(days=30)
    c1, c2 = st.columns(2)
    range_start = c1.date_input("Başlangıç", value=default_start, max_value=as_of, key="range_start")
    range_end = c2.date_input("Bitiş", value=as_of, max_value=as_of, key="range_end")
    if range_start >= range_end:
        st.error("Başlangıç tarihi bitiş tarihinden önce olmalı.")
    else:
        with st.spinner("Hesaplanıyor..."):
            rdf = range_table(group, range_start, range_end)
        if rdf.empty:
            st.warning("Veri alınamadı.")
        else:
            rdisp = rdf.copy()
            rdisp["GETİRİ"] = rdf["GETİRİ"].map(fmt_pct)
            st.dataframe(rdisp, use_container_width=True, hide_index=True)

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
    ydisp["SIRA DEĞ."] = "-"
    st.dataframe(
        ydisp[["FON KODU", "FON ADI", "YÖN. ÜCRETİ", "BÜYÜKLÜK", "YTD GETİRİ", "SIRA DEĞ."]],
        use_container_width=True,
        hide_index=True,
    )

st.caption(
    "Veriler tefas.gov.tr üzerinden çekilmektedir (fonGnlBlgSiraliGetir, "
    "dagilimSiraliGetirT, fonGetiriBazliBilgiGetir, fonYonetimBazliBilgiGetir, "
    "fonProfilBilgiGetir, fonBilgiGetir uçları). Brüt getiri ve sıra değişimi "
    "gibi bazı alanlar TEFAS'ın herkese açık servislerinde yer almadığı için "
    "gösterilmemektedir."
)
