"""dump_bfw_price_changes 單元測試（純函式，不碰 COM/網路/檔案系統）。

重點：
- 2026-08-28 橡膠 nRef 改寫事故 regression（已收盤分支昨結必須「鏈 history 優先」）。
- 最活絡月自動換月（成交量判準）＋候選選擇（HOT/active 錨、LTD 強制滾）。
- 雙合約結算鏈 state schema 遷移（舊 {code, history} → {active_code, chains}）與修剪。
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "dump_bfw_price_changes", REPO / "scripts" / "dump_bfw_price_changes.py")
dump = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dump)


# ---------------------------------------------------------------- 任務 1：已收盤分支昨結改鏈優先

def _rubber_entry():
    """2026-08-28 橡膠實例：state 已存 08-25/08-26 的正確結算。"""
    return {
        "active_code": "STF2609",
        "chains": {"STF2609": {"history": {"2026-08-25": 235.3, "2026-08-26": 236.3}}},
    }


RUBBER_Q = {"close": 239.0, "ref": 238.8, "settle": 239.0, "day": 20260827}


class TestChainChangesClosedBranch:
    def test_rubber_nref_rewrite_regression(self, capsys):
        """🔴 橡膠事故 regression：SGX 收盤後把 nRef 改寫成 238.8（昨結實為 236.3）。

        已收盤分支必須用鏈上昨結 236.3 算出 +1.1426%，不是 nRef 的 +0.0838%。
        """
        entry = _rubber_entry()
        out = dump._chain_changes("rubber", "STF2609", dict(RUBBER_Q),
                                  date(2026, 8, 28), entry, "SGX,STF2609")
        assert out["daily_pct"] == 1.1426
        assert out["daily_pct"] != round((239.0 / 238.8 - 1) * 100, 4)  # 0.0838＝bug 值
        # 本日結算照寫進鏈（nSettle 已驗證正確）
        assert entry["chains"]["STF2609"]["history"]["2026-08-27"] == 239.0
        # nRef 與鏈值不一致要有 warning 診斷訊號
        assert "nRef" in capsys.readouterr().out

    def test_nref_consistent_no_warning(self, capsys):
        """nRef 與鏈上昨結一致（正常日）→ 值相同、無 warning。"""
        entry = _rubber_entry()
        q = dict(RUBBER_Q, ref=236.3)
        out = dump._chain_changes("rubber", "STF2609", q,
                                  date(2026, 8, 28), entry, "SGX,STF2609")
        assert out["daily_pct"] == 1.1426
        assert "⚠️" not in capsys.readouterr().out

    def test_nref_fallback_when_chain_empty(self):
        """鏈上沒有昨結（冷啟動）→ 已收盤分支 fallback 用 nRef（原行為保留）。"""
        entry = {"active_code": "STF2609", "chains": {}}
        out = dump._chain_changes("rubber", "STF2609", dict(RUBBER_Q),
                                  date(2026, 8, 28), entry, "SGX,STF2609")
        assert out["daily_pct"] == round((239.0 / 238.8 - 1) * 100, 4)

    def test_nref_fallback_when_chain_stale(self):
        """鏈上最近一筆距結算日 > 4 日曆天（長假/斷檔）→ 不用鏈值，fallback nRef。"""
        entry = {"active_code": "STF2609",
                 "chains": {"STF2609": {"history": {"2026-08-18": 230.0}}}}
        out = dump._chain_changes("rubber", "STF2609", dict(RUBBER_Q),
                                  date(2026, 8, 28), entry, "SGX,STF2609")
        assert out["daily_pct"] == round((239.0 / 238.8 - 1) * 100, 4)

    def test_cold_chain_rewritten_nref_leaves_blank(self):
        """🔴 冷鏈 + ref==settle（收盤後 nRef 被改寫簽名，NYM/CME 09:00 實測）→
        不得算出 settle/ref=+0.00% 假值，必須鏈未接上（讓上層退最後成交鏈）。"""
        entry = {"active_code": "HO2610", "chains": {}}
        q = {"close": 41633.0, "ref": 41753.0, "settle": 41753.0, "day": 20260827}
        out = dump._chain_changes("heating_oil", "HO2610", q, date(2026, 8, 28),
                                  entry, "NYM,HO2610")
        assert out["daily_pct"] is None
        # 本日結算照樣入鏈（settle 是真值），明日起有值
        assert entry["chains"]["HO2610"]["history"]["2026-08-27"] == 41753.0

    def test_cold_chain_distinct_nref_still_falls_back(self):
        """ref ≠ settle（未被改寫，06:30 生產時點常態）→ nRef fallback 照常可用。"""
        entry = {"active_code": "OJF2611", "chains": {}}
        q = {"close": 147.65, "ref": 146.35, "settle": 147.6, "day": 20260827}
        out = dump._chain_changes("orange_juice", "OJF2611", q, date(2026, 8, 28),
                                  entry, "ICEUS,OJF2611")
        assert out["daily_pct"] == round((147.6 / 146.35 - 1) * 100, 4)  # +0.8541

    def test_settle_missing_uses_ref_as_value(self):
        """已收盤但 nSettle=0（哨兵）→ 本日值退用 nRef（原行為保留）。"""
        entry = _rubber_entry()
        q = dict(RUBBER_Q, settle=0)
        out = dump._chain_changes("rubber", "STF2609", q,
                                  date(2026, 8, 28), entry, "SGX,STF2609")
        # settle_val = ref = 238.8；昨結 = 鏈 236.3
        assert out["daily_pct"] == round((238.8 / 236.3 - 1) * 100, 4)


class TestChainChangesIntraday:
    def test_intraday_uses_history(self):
        """盤中（day >= as_of）：nRef=今日的昨結，與鏈上前一交易日結算相除。"""
        entry = {"active_code": "C2609",
                 "chains": {"C2609": {"history": {"2026-08-26": 514.0}}}}
        q = {"close": 512.0, "ref": 510.25, "settle": 0, "day": 20260828}
        out = dump._chain_changes("corn", "C2609", q, date(2026, 8, 28),
                                  entry, "CBOT,C2609")
        assert out["daily_pct"] == round((510.25 / 514.0 - 1) * 100, 4)
        assert entry["chains"]["C2609"]["history"]["2026-08-27"] == 510.25

    def test_intraday_cold_start_leaves_blank(self):
        """盤中且鏈空 → 留空（絕不拿 nRef 自己除自己）。"""
        entry = {"active_code": "C2609", "chains": {}}
        q = {"close": 512.0, "ref": 510.25, "settle": 0, "day": 20260828}
        out = dump._chain_changes("corn", "C2609", q, date(2026, 8, 28),
                                  entry, "CBOT,C2609")
        assert out["daily_pct"] is None
        assert entry["chains"]["C2609"]["history"]["2026-08-27"] == 510.25

    def test_weekly_from_chain_history(self):
        """鏈滿 7 日曆天 → 週漲跌從鏈算。"""
        entry = {"active_code": "C2609", "chains": {"C2609": {"history": {
            "2026-08-19": 500.0, "2026-08-26": 514.0}}}}
        q = {"close": 512.0, "ref": 510.25, "settle": 0, "day": 20260828}
        out = dump._chain_changes("corn", "C2609", q, date(2026, 8, 28),
                                  entry, "CBOT,C2609")
        # settle_date=08-27，week_ago=08-20 → 基準取 08-19
        assert out["weekly_pct"] == round((510.25 / 500.0 - 1) * 100, 4)

    def test_intraday_stale_ref_prefers_stored_settle(self):
        """🔴 盤中 nRef 過時（DX 實測：day 已滾 08-28、ref 還停在 08-26 結算 99.09）→
        settle_val 用鏈上既有的正式結算 99.092，且不得被過時 ref 蓋掉。"""
        entry = {"active_code": "DX2609", "chains": {"DX2609": {"history": {
            "2026-08-26": 99.09, "2026-08-27": 99.092}}}}
        q = {"close": 99.065, "ref": 99.09, "settle": 99.092, "day": 20260828}
        out = dump._chain_changes("dollar_index", "DX2609", q, date(2026, 8, 28),
                                  entry, "ICEUS,DX2609")
        assert out["daily_pct"] == round((99.092 / 99.09 - 1) * 100, 4)  # +0.002 非 0.0
        assert entry["chains"]["DX2609"]["history"]["2026-08-27"] == 99.092  # 未被蓋

    def test_closed_settle_overwrites_history(self):
        """已收盤 nSettle 有值＝權威 → 覆蓋鏈上舊值（結算修正照走）。"""
        entry = {"active_code": "C2609",
                 "chains": {"C2609": {"history": {"2026-08-27": 509.0}}}}
        q = {"close": 510.0, "ref": 514.0, "settle": 510.25, "day": 20260827}
        dump._feed_chain(entry, "C2609", q, date(2026, 8, 28))
        assert entry["chains"]["C2609"]["history"]["2026-08-27"] == 510.25

    def test_snapshot_missing_returns_null(self):
        entry = {"active_code": "C2609", "chains": {}}
        out = dump._chain_changes("corn", "C2609", None, date(2026, 8, 28),
                                  entry, "CBOT,C2609")
        assert out["daily_pct"] is None and out["weekly_pct"] is None


# ---------------------------------------------------------------- 任務 2：成交量判準滾月

def _bars(spec: dict[str, tuple[float, float | None]]):
    return {date.fromisoformat(d): {"close": c, "volume": v} for d, (c, v) in spec.items()}


class TestShouldRoll:
    AS_OF = date(2026, 8, 28)

    def test_next_dominates_two_days_rolls(self):
        """橘子汁實例（Yahoo 08-26/08-27 量）：Nov 連兩完成日 > Sep → 滾。"""
        front = _bars({"2026-08-26": (140.95, 945), "2026-08-27": (137.35, 1096)})
        nxt = _bars({"2026-08-26": (146.35, 1422), "2026-08-27": (147.60, 1370)})
        assert dump._should_roll(front, nxt, self.AS_OF) is True

    def test_only_latest_day_dominates_no_roll(self):
        front = _bars({"2026-08-26": (140.95, 2000), "2026-08-27": (137.35, 1096)})
        nxt = _bars({"2026-08-26": (146.35, 1422), "2026-08-27": (147.60, 1370)})
        assert dump._should_roll(front, nxt, self.AS_OF) is False

    def test_zero_volume_days_excluded(self):
        """零成交 bar（結算順延平 bar）不計入比較 → 有效共同日不足 2 → 不切。"""
        front = _bars({"2026-08-26": (140.95, 0), "2026-08-27": (137.35, 1096)})
        nxt = _bars({"2026-08-26": (146.35, 1422), "2026-08-27": (147.60, 1370)})
        assert dump._should_roll(front, nxt, self.AS_OF) is False

    def test_insufficient_next_rows_no_roll(self):
        front = _bars({"2026-08-26": (140.95, 945), "2026-08-27": (137.35, 1096)})
        nxt = _bars({"2026-08-27": (147.60, 1370)})
        assert dump._should_roll(front, nxt, self.AS_OF) is False

    def test_incomplete_today_bar_excluded(self):
        """as_of 當天的 bar（進行中 session）不計入。"""
        front = _bars({"2026-08-27": (137.35, 1096), "2026-08-28": (137.0, 10)})
        nxt = _bars({"2026-08-27": (147.60, 1370), "2026-08-28": (147.0, 5000)})
        assert dump._should_roll(front, nxt, self.AS_OF) is False

    def test_missing_volume_column_no_roll(self):
        """來源沒給 volume 欄（None）→ 視同不可比 → 不切。"""
        front = _bars({"2026-08-26": (140.95, None), "2026-08-27": (137.35, None)})
        nxt = _bars({"2026-08-26": (146.35, 1422), "2026-08-27": (147.60, 1370)})
        assert dump._should_roll(front, nxt, self.AS_OF) is False


class TestMonthCodesAndCandidates:
    AS_OF = date(2026, 8, 28)
    CATALOG = {
        "OJF2609": {"exch": "ICEUS", "name": "OJ Sep", "order_code": "OJ_202609",
                    "ltd": "20260910"},
        "OJF2611": {"exch": "ICEUS", "name": "OJ Nov", "order_code": "OJ_202611",
                    "ltd": "20261110"},
        "OJF2701": {"exch": "ICEUS", "name": "OJ Jan", "order_code": "OJ_202701",
                    "ltd": "20270110"},
        "OJF2608": {"exch": "ICEUS", "name": "OJ Aug expired", "order_code": "OJ_202608",
                    "ltd": "20260810"},
        "OJFBAD": {"exch": "ICEUS", "name": "bad", "order_code": "OJ_XXX", "ltd": "0"},
        "C2609": {"exch": "CBOT", "name": "Corn Sep", "order_code": "C_202609",
                  "ltd": "20260914"},
    }

    def test_month_codes_sorted_and_filtered(self):
        months = dump._month_codes(self.CATALOG, "OJF", self.AS_OF)
        assert months == ["OJF2609", "OJF2611", "OJF2701"]  # 過期/壞 LTD 已濾

    def test_ltd_forced_roll_excludes_near_expiry(self):
        """LTD < as_of+3 的月份不進候選（強制滾保險）。"""
        months = dump._month_codes(self.CATALOG, "OJF", date(2026, 9, 9))
        assert months == ["OJF2611", "OJF2701"]

    def test_pick_candidates_default_front(self):
        months = ["OJF2609", "OJF2611", "OJF2701"]
        assert dump._pick_candidates(months, [None, None]) == ("OJF2609", "OJF2611")

    def test_pick_candidates_active_anchor_wins(self):
        """state 已滾到 Nov、HOT 仍指 Sep → 錨取較晚者（單向不回滾）。"""
        months = ["OJF2609", "OJF2611", "OJF2701"]
        assert dump._pick_candidates(months, ["OJF2611", "OJF2609"]) == ("OJF2611", "OJF2701")

    def test_pick_candidates_hot_anchor(self):
        months = ["OJF2609", "OJF2611", "OJF2701"]
        assert dump._pick_candidates(months, [None, "OJF2609"]) == ("OJF2609", "OJF2611")

    def test_pick_candidates_last_month_no_next(self):
        months = ["OJF2609", "OJF2611", "OJF2701"]
        assert dump._pick_candidates(months, ["OJF2701", None]) == ("OJF2701", None)

    def test_pick_candidates_stale_anchor_ignored(self):
        """錨已不在候選（LTD 濾掉）→ 從第一個可用月起（＝強制滾月）。"""
        months = ["OJF2611", "OJF2701"]
        assert dump._pick_candidates(months, ["OJF2609", "OJF2609"]) == ("OJF2611", "OJF2701")


# ---------------------------------------------------------------- 任務 3：state schema 遷移/修剪

class TestStateMigrationAndPrune:
    def test_migrate_old_schema(self):
        old = {"code": "STF2609", "history": {"2026-08-26": 236.3},
               "updated": "2026-08-28T06:31:35"}
        new = dump._migrate_settle_entry(old)
        assert new["active_code"] == "STF2609"
        assert new["chains"]["STF2609"]["history"] == {"2026-08-26": 236.3}
        assert new["updated"] == "2026-08-28T06:31:35"

    def test_migrate_idempotent(self):
        entry = _rubber_entry()
        assert dump._migrate_settle_entry(entry) is entry

    def test_migrate_empty(self):
        new = dump._migrate_settle_entry({})
        assert new["active_code"] is None and new["chains"] == {}

    def test_prune_drops_untracked_chains_and_old_history(self):
        entry = {"active_code": "OJF2611", "chains": {
            "OJF2609": {"history": {"2026-08-26": 140.95}},
            "OJF2611": {"history": {"2026-07-01": 130.0, "2026-08-26": 146.35}},
        }}
        dump._prune_entry(entry, {"OJF2611", "OJF2701"}, date(2026, 8, 28))
        assert "OJF2609" not in entry["chains"]
        assert entry["chains"]["OJF2611"]["history"] == {"2026-08-26": 146.35}

    def test_feed_chain_inactive_candidate(self):
        """非 active 候選也要餵鏈（切換日昨結已在鏈上＝無縫）。"""
        entry = {"active_code": "OJF2609", "chains": {}}
        q = {"close": 147.6, "ref": 146.35, "settle": 147.6, "day": 20260827}
        fed = dump._feed_chain(entry, "OJF2611", q, date(2026, 8, 28))
        assert fed == (date(2026, 8, 27), date(2026, 8, 27), 147.6)
        assert entry["chains"]["OJF2611"]["history"]["2026-08-27"] == 147.6

    def test_feed_chain_intraday_weekend_skip(self):
        """盤中分支：settle_date=前一平日（週一 → 上週五）。"""
        entry = {"active_code": "C2609", "chains": {}}
        q = {"close": 512.0, "ref": 510.25, "settle": 0, "day": 20260831}  # 週一
        fed = dump._feed_chain(entry, "C2609", q, date(2026, 8, 31))
        assert fed[1] == date(2026, 8, 28)  # 上週五
        assert entry["chains"]["C2609"]["history"]["2026-08-28"] == 510.25

    def test_feed_chain_invalid_snapshot(self):
        entry = {"active_code": "C2609", "chains": {}}
        assert dump._feed_chain(entry, "C2609", None, date(2026, 8, 28)) is None
        assert dump._feed_chain(entry, "C2609", {"ref": 0, "day": 20260827},
                                date(2026, 8, 28)) is None
        assert dump._feed_chain(entry, "C2609", {"ref": 1.0, "day": 20261399},
                                date(2026, 8, 28)) is None
        assert entry["chains"] == {}


# ---------------------------------------------------------------- KLine 解析（volume 擴充）

class TestParseKline:
    def test_bars_with_volume(self):
        rows = ["2026/08/26, 140.00, 141.00, 139.00, 140.95, 945",
                "2026/08/27, 140.50, 141.50, 137.00, 137.35, 1096"]
        bars = dump._parse_kline_bars(rows)
        assert bars[date(2026, 8, 26)] == {"close": 140.95, "volume": 945.0}
        assert bars[date(2026, 8, 27)]["volume"] == 1096.0

    def test_bars_without_volume_column(self):
        bars = dump._parse_kline_bars(["2026/08/26, 1.0, 1.1, 0.9, 1.05"])
        assert bars[date(2026, 8, 26)] == {"close": 1.05, "volume": None}

    def test_closes_wrapper_unchanged(self):
        rows = ["2026/08/26, 140.00, 141.00, 139.00, 140.95, 945",
                "garbage", "10:30, 1, 2, 3, 4, 5"]
        closes = dump._parse_kline_rows(rows)
        assert closes == {date(2026, 8, 26): 140.95}
