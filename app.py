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
def _history(fund_code: str, start: date, end: date, fund_type: str) -> pd.DataFrame:
    try:
        return tf.fetch_fund_history(fund_code, start, end, fund_type)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _allocation(fund_code: str, on: date, fund_type: str) -> pd.DataFrame:
    try:
        return tf.fetch_fund_allocation(fund_code, on, fund_type)
    except Exception:
        return pd.DataFrame()


def daily_table(group: PeerGroup, as_of: date) -> pd.DataFrame:
    rows = []
    start = as_of - timedelta(days=10)
    for code in group.funds:
        hist = _history(code, start, as_of, group.fund_type)
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
    rows = []
    for code in group.funds:
        hist = _history(code, start, end, group.fund_type)
        ret = tf.compute_range_return(hist)
        name = hist.iloc[-1]["FONUNVAN"] if not hist.empty else "N/A"
        rows.append({"FON KODU": code, "FON ADI": name, "GETİRİ": ret})
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("GETİRİ", ascending=False, na_position="last").reset_index(drop=True)
    return df


def ytd_table(group: PeerGroup, as_of: date) -> pd.DataFrame:
    jan1 = date(as_of.year, 1, 1)
    rows = []
    for code in group.funds:
        hist = _history(code, jan1, as_of, group.fund_type)
        ret = tf.compute_range_return(hist)
        size = hist.iloc[-1]["PORTFOYBUYUKLUK"] if not hist.empty else None
        name = hist.iloc[-1]["FONUNVAN"] if not hist.empty else "N/A"
        rows.append(
            {
                "FON KODU": code,
                "FON ADI": name,
                "YÖN. ÜCRETİ": None,
                "BÜYÜKLÜK": size,
                "YTD GETİRİ": ret,
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

    st.caption("Varlık dağılımı (ve isteğe bağlı değişim) için bir fon seçin.")
    picked = st.selectbox("Fon", options=group.funds, key="alloc_pick")
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
with st.spinner("YTD hesaplanıyor..."):
    ydf = ytd_table(group, as_of)
if ydf.empty:
    st.warning("Veri alınamadı.")
else:
    ydisp = ydf.copy()
    ydisp["BÜYÜKLÜK"] = ydf["BÜYÜKLÜK"].map(fmt_size)
    ydisp["YTD GETİRİ"] = ydf["YTD GETİRİ"].map(fmt_pct)
    ydisp["YÖN. ÜCRETİ"] = "-"
    ydisp["SIRA DEĞ."] = "-"
    st.dataframe(
        ydisp[["FON KODU", "FON ADI", "YÖN. ÜCRETİ", "BÜYÜKLÜK", "YTD GETİRİ", "SIRA DEĞ."]],
        use_container_width=True,
        hide_index=True,
    )

st.caption(
    "Veriler tefas.gov.tr üzerinden çekilmektedir (BindHistoryInfo / "
    "BindHistoryAllocation uçları). Yönetim ücreti ve brüt getiri gibi bazı "
    "alanlar TEFAS'ın herkese açık geçmiş veri servisinde yer almadığı için "
    "gösterilmemektedir."
)
