"""Peer-group definitions.

The sidebar mirrors the original TEFAS Fon Takip navigation: a category
(e.g. "YERLI HISSE") contains several peer groups (e.g. "ALU Peers"), and
each peer group is a fixed list of TEFAS fund codes that get compared
side by side.

``fund_type`` is "YAT" for regular securities mutual funds and "EMK" for
pension (emeklilik) funds — TEFAS uses different endpoints/params for the
two, so it must be set per group.

Only a handful of groups have their fund codes filled in for now (seeded
from the reference screenshots). The rest of the nav tree is present with
an empty fund list so the sidebar/structure matches the target site; add
codes to ``funds`` as they're identified and the tables populate
automatically — no other code changes needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PeerGroup:
    name: str
    funds: list[str] = field(default_factory=list)
    fund_type: str = "YAT"  # "YAT": securities mutual fund, "EMK": pension fund


@dataclass
class Category:
    name: str
    groups: list[PeerGroup] = field(default_factory=list)


CATEGORIES: list[Category] = [
    Category(
        "BORÇLANMA ARAÇLARI VE KIYMETLİ MADENLER",
        [
            PeerGroup("AMZ Peers"),
            PeerGroup("AMZ Peers XL"),
            PeerGroup(
                "YAK-YSU Peers",
                [
                    "TKF", "TCD", "GMA", "TE3", "KRF", "YAK", "NNF",
                    "IBP", "TKK", "YSU", "HSA", "ADE", "TGA", "HPD", "AAK",
                ],
            ),
            PeerGroup("PKT Peers"),
            PeerGroup("AZK-AZA Peers"),
            PeerGroup("AZL Peers"),
            PeerGroup("YBS Peers"),
            PeerGroup("YOT Peers"),
            PeerGroup("YZG Peers"),
            PeerGroup("YGM Peers"),
            PeerGroup("YKT Peers"),
            PeerGroup("YTV Peers"),
            PeerGroup("YFV Peers"),
            PeerGroup("YPT Peers"),
            PeerGroup("YIK Peers"),
            PeerGroup("YVB-YPK Peers"),
            PeerGroup("YHT-YDK Peers"),
            PeerGroup("Yapı Likitler"),
        ],
    ),
    Category(
        "EUROBOND",
        [
            PeerGroup("AMG-AZD-AMR Peers"),
            PeerGroup(
                "YBE Peers",
                ["YBE", "DBH", "FPE", "GPA", "FUB", "AKE"],
            ),
            PeerGroup("YPL-YNK-YOA Peers"),
            PeerGroup("YPL-YNK-YOA USD Peers"),
            PeerGroup("YVG Peers"),
            PeerGroup("YVG EUR Peers"),
            PeerGroup("YTY Peers"),
            PeerGroup("YTY EUR Peers"),
            PeerGroup("YJY-YP4-YMD Peers"),
            PeerGroup("YJY-YP4-YMD USD Peers"),
        ],
    ),
    Category(
        "EXOTICS",
        [
            PeerGroup(
                "Exotic Peers",
                [
                    "PKZ", "PCS", "THF", "PHE", "LTL", "TLY", "PUK",
                    "VPS", "DFI", "TP2", "PRY", "MT2", "PBR",
                ],
            ),
        ],
    ),
    Category(
        "YABANCI HİSSE",
        [
            PeerGroup(
                "YAY Peers",
                ["GUH", "YAY", "AFT", "TFF"],
            ),
            PeerGroup("YTD Peers"),
            PeerGroup("YJH Peers"),
            PeerGroup("YJK Peers XL"),
            PeerGroup("YJK Peers"),
            PeerGroup("YSO Peers"),
            PeerGroup("YLO Peers"),
            PeerGroup("YPC Peers"),
            PeerGroup("YZC Peers"),
        ],
    ),
    Category(
        "YERLİ HİSSE",
        [
            PeerGroup(
                "ALU Peers",
                [
                    "ALU", "CHG", "GHJ", "ALJ", "MHR", "VGF", "VVA",
                    "AJR", "AJA", "AHL", "BPI", "FIC",
                ],
                fund_type="EMK",
            ),
            PeerGroup("YHS Peers"),
            PeerGroup("YUB Peers"),
            PeerGroup("YDI Peers"),
            PeerGroup("YHI Peers"),
            PeerGroup("BIG-YAS Peers"),
            PeerGroup("YEF Peers"),
            PeerGroup("YLE Peers"),
        ],
    ),
    Category(
        "ÖPY",
        [],
    ),
]


def find_group(group_name: str) -> PeerGroup | None:
    for category in CATEGORIES:
        for group in category.groups:
            if group.name == group_name:
                return group
    return None


def find_fund_type(fund_code: str) -> str:
    """Fund type ("YAT"/"EMK") for a code, looked up from whichever
    configured group first lists it. Defaults to "YAT" if the code isn't in
    any group (e.g. reached via a hand-edited URL)."""
    for category in CATEGORIES:
        for group in category.groups:
            if fund_code in group.funds:
                return group.fund_type
    return "YAT"
