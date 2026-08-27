"""Standalone smoke test for the TEFAS endpoints, meant to run in an
environment with real internet access (e.g. GitHub Actions), since the
interactive dev sandbox's egress policy blocks tefas.gov.tr. Prints raw
results so field names/shapes can be verified against tefas_client.py.
"""

from datetime import date, timedelta

import tefas_client as tf


def main() -> None:
    end = tf.last_business_day()
    start = end - timedelta(days=10)

    print(f"=== fetch_fund_history('YAK', {start}, {end}) ===")
    hist = tf.fetch_fund_history("YAK", start, end)
    print(hist)
    print()
    print("columns:", list(hist.columns))
    print()
    daily_return, size, name = tf.compute_daily_return(hist)
    print(f"daily_return={daily_return} size={size} name={name}")

    print()
    print(f"=== fetch_fund_allocation('YAK', {end}) ===")
    alloc = tf.fetch_fund_allocation("YAK", end)
    print(alloc)
    print()
    print("columns:", list(alloc.columns))

    print()
    print("=== EMK fund type: fetch_fund_history('ALU', ...) ===")
    hist_emk = tf.fetch_fund_history("ALU", start, end, fund_type="EMK")
    print(hist_emk)
    print("columns:", list(hist_emk.columns))

    print()
    print("=== fetch_all_fund_returns('YAT') filtered to YAK ===")
    returns_df = tf.fetch_all_fund_returns("YAT")
    print("total rows:", len(returns_df))
    if not returns_df.empty:
        row = returns_df[returns_df["fonKodu"] == "YAK"]
        print(row.to_dict("records"))

    print()
    print("=== fetch_management_fees('YAT') filtered to YAK ===")
    fees_df = tf.fetch_management_fees("YAT")
    print("total rows:", len(fees_df))
    if not fees_df.empty:
        row = fees_df[fees_df["fonKodu"] == "YAK"]
        print(row.to_dict("records"))

    print()
    print("=== fetch_fund_profile('YAK') ===")
    print(tf.fetch_fund_profile("YAK"))

    print()
    print("=== fetch_fund_bilgi('YAK') ===")
    print(tf.fetch_fund_bilgi("YAK"))

    print()
    print("=== fund detail page pipeline: YAK flow history (targeted windows) + net flows ===")
    yak_hist = tf.fetch_fund_flow_history("YAK", end)
    print("rows:", len(yak_hist))
    if not yak_hist.empty:
        last_idx = len(yak_hist) - 1
        gunluk_idx = last_idx - 1 if last_idx >= 1 else None
        haftalik_idx = tf.find_row_on_or_before(yak_hist, end - timedelta(days=7))
        yil_basi_idx = 0 if last_idx >= 1 else None
        print("gunluk net giris:", tf.compute_net_flow(yak_hist, gunluk_idx) if gunluk_idx is not None else None)
        print("haftalik net giris:", tf.compute_net_flow(yak_hist, haftalik_idx) if haftalik_idx is not None else None)
        print("yilbasindan net giris:", tf.compute_net_flow(yak_hist, yil_basi_idx) if yil_basi_idx is not None else None)

    print()
    print("=== 30-day allocation for YAK (detail page table) ===")
    alloc_30 = tf.fetch_fund_allocation("YAK", end, lookback_days=27)
    print("rows:", len(alloc_30))
    if not alloc_30.empty:
        numeric_cols = [c for c in alloc_30.columns if c not in ("TARIH", "FONKODU") and alloc_30[c].dtype.kind in "fi"]
        nonzero_cols = [c for c in numeric_cols if (alloc_30[c].fillna(0) != 0).any()]
        print("nonzero asset columns:", nonzero_cols)

    print()
    print("=== bulk history: INFO_URL with fonKodu=None (whole YAT universe, 1 day) ===")
    body = tf._build_body(None, end, end, "YAT")
    print("request body:", body)
    df_all = tf._post(tf.INFO_URL, body, tf.INFO_FIELDS)
    print("rows:", len(df_all))
    if not df_all.empty:
        print(df_all.head(3))
        print("PKZ present:", (df_all["FONKODU"] == "PKZ").any())
        print("YAK present:", (df_all["FONKODU"] == "YAK").any())


if __name__ == "__main__":
    main()
