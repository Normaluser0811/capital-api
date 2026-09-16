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


# ---------------------------------------------------------------- SPOT_INDEX 混合法守衛

class TestHybridIndexNrefRollover:
    """🔴 2026-08-28 06:31 事故：INDEX 頁收盤後把 nRef 滾成昨收（nClose==nRef），
    未開盤分支昨收/前日收同值 → KOSPI/NI225 發布 +0.00% 假值（真值 +1.53%/-0.20%）。"""

    KOSPI_CLOSES = {date(2026, 8, 25): 6742.74, date(2026, 8, 26): 6808.21,
                    date(2026, 8, 27): 6912.37}

    def test_kospi_rolled_nref_regression(self):
        """nClose==nRef 簽名 → 前日收退日K 完成列（08-26），算出 +1.53% 非 0.00%。"""
        q = {"close": 6912.37, "ref": 6912.37, "settle": 0, "day": 20260827}
        out = dump._hybrid_index_changes(q, dict(self.KOSPI_CLOSES),
                                         date(2026, 8, 28), "INDEX,KOSPI")
        assert out["daily_pct"] == round((6912.37 / 6808.21 - 1) * 100, 4)
        assert out["daily_pct"] != 0.0

    def test_unrolled_nref_unchanged(self):
        """ref ≠ close（HHHSI 06:31 常態）→ 原路徑：前日收=nRef。"""
        closes = {date(2026, 8, 25): 25511.10, date(2026, 8, 26): 25652.97,
                  date(2026, 8, 27): 25565.74}
        q = {"close": 25565.74, "ref": 25652.97, "settle": 0, "day": 20260827}
        out = dump._hybrid_index_changes(q, closes, date(2026, 8, 28), "INDEX,HHHSI")
        assert out["daily_pct"] == round((25565.74 / 25652.97 - 1) * 100, 4)  # -0.34

    def test_rolled_nref_without_kline_history_blank(self):
        """簽名命中但日K 無更早完成列 → 留空，不出 0.00%。"""
        q = {"close": 6912.37, "ref": 6912.37, "settle": 0, "day": 20260827}
        out = dump._hybrid_index_changes(q, {date(2026, 8, 27): 6912.37},
                                         date(2026, 8, 28), "INDEX,KOSPI")
        assert out["daily_pct"] is None

    def test_intraday_branch_unaffected(self):
        """開盤中分支（day >= as_of）不受守衛影響：昨收=nRef、前日=日K。"""
        q = {"close": 6900.0, "ref": 6912.37, "settle": 0, "day": 20260828}
        out = dump._hybrid_index_changes(q, dict(self.KOSPI_CLOSES),
                                         date(2026, 8, 28), "INDEX,KOSPI")
        assert out["daily_pct"] == round((6912.37 / 6808.21 - 1) * 100, 4)


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


class TestDomesticRefIsPrevDay:
    """國內線的 nRef 是「nTradingDay 前一交易日」的結算，不是當天的（2026-09-16）。

    事故：2026-09-16 06:57 的 dump 把台指期日漲跌算成 +0.00%，模型寫出
    「結算日多空拉鋸持平」並發佈到 Notion。鏈上實際是

        TX10AM: {"2026-09-14": 45903.0, "2026-09-15": 45903.0}
        TX11AM: {"2026-09-14": 46032.0, "2026-09-15": 46032.0}

    用期交所官方 raw_taifex.futures_daily 驗證：45903.0 與 46032.0 正是 09-14 的
    結算價（TX 202610／202611）⇒ 09-15 那格是 09-14 的複製品。

    機制：_domestic_snapshot 的 settle 恆為 None（SKSTOCKLONG 沒有 nSettlePrice 欄），
    於是 _feed_chain 已收盤分支走到第三段退回 q["ref"]，但三段語意不同——
    settle 是 day_d 當天的結算、ref 是 day_d 前一天的結算——日期卻一律標成 day_d。

    為什麼 09-15 對、09-16 錯：09-15 10:22 開盤後跑，nTradingDay=09-15、as_of=09-15
    ⇒ 走盤中分支（settle_date = day_d − 1）⇒ 正確；09-16 06:57 開盤前跑，
    TAIFEX 的 nTradingDay 要到 08:45 才滾、仍是 09-15，as_of=09-16 ⇒ 走已收盤分支
    ⇒ 貼錯日期。日報固定 06:30 觸發、永遠早於 08:45 ⇒ 台指期每天都會踩。

    為什麼只修國內不動海外：nRef 語意逐交易所而異，不可一律前移一天。
    SGX 收盤後把 nRef 改寫成當日結算（橡膠 2026-08-28；既有的
    test_settle_missing_uses_ref_as_value 測的就是那個刻意的正確行為）；
    NYMEX/CME 則改寫成 = settle（_chain_changes 已有棄用判斷）。
    所以改動只由 _domestic_snapshot 帶的 ref_is_prev_day 旗標驅動。
    """

    TAIEX_Q = {"day": 20260915, "ref": 45903.0, "settle": None,
               "ref_is_prev_day": True}

    def test_ref_lands_on_the_previous_trading_day_not_day_d(self):
        entry = {"active_code": "TX10AM", "chains": {}}
        dump._feed_chain(entry, "TX10AM", dict(self.TAIEX_Q), date(2026, 9, 16))
        hist = entry["chains"]["TX10AM"]["history"]
        assert "2026-09-15" not in hist, "09-15 的結算還沒拿到，不可以憑空寫一格"
        assert hist == {"2026-09-14": 45903.0}

    def test_the_actual_incident_produces_blank_not_fake_zero(self):
        """事故重演：06:57 跑 ⇒ 日漲跌必須留空，不可以是 +0.00%。"""
        entry = {"active_code": "TX10AM",
                 "chains": {"TX10AM": {"history": {"2026-09-14": 45903.0}}}}
        out = dump._chain_changes("taiex", "TX10AM", dict(self.TAIEX_Q),
                                  date(2026, 9, 16), entry, "TAIFEX,TX10AM")
        assert out["daily_pct"] is None, f"應留空，實際 {out['daily_pct']}"
        assert entry["chains"]["TX10AM"]["history"] == {"2026-09-14": 45903.0}

    def test_after_market_open_the_real_value_comes_out(self):
        """08:45 後 nTradingDay 滾成 09-16、nRef 變成 09-15 真實結算 ⇒ 算得出來。

        這條證明修法不是把台指期永久留空，只是拒絕在拿不到資料時瞎猜。
        """
        entry = {"active_code": "TX10AM",
                 "chains": {"TX10AM": {"history": {"2026-09-14": 45903.0}}}}
        q = {"day": 20260916, "ref": 46150.0, "settle": None, "ref_is_prev_day": True}
        out = dump._chain_changes("taiex", "TX10AM", q,
                                  date(2026, 9, 16), entry, "TAIFEX,TX10AM")
        assert out["daily_pct"] == round((46150.0 / 45903.0 - 1) * 100, 4)
        assert entry["chains"]["TX10AM"]["history"]["2026-09-15"] == 46150.0

    def test_previous_trading_day_skips_weekend(self):
        """day_d − 1 要跳週末：週一(09-14)的前一交易日是週五(09-11)。"""
        entry = {"active_code": "TX10AM", "chains": {}}
        q = {"day": 20260914, "ref": 46372.0, "settle": None, "ref_is_prev_day": True}
        dump._feed_chain(entry, "TX10AM", q, date(2026, 9, 15))
        assert entry["chains"]["TX10AM"]["history"] == {"2026-09-11": 46372.0}

    def test_overseas_without_the_flag_is_completely_unchanged(self):
        """沒帶旗標的海外快照行為逐字不變——橡膠那條路不可以被動到。"""
        entry = {"active_code": "STF2609", "chains": {}}
        q = {"close": 239.0, "ref": 238.8, "settle": 0, "day": 20260827}
        dump._feed_chain(entry, "STF2609", q, date(2026, 8, 28))
        assert entry["chains"]["STF2609"]["history"] == {"2026-08-27": 238.8}, \
            "海外仍應掛在 day_d 當天"


# ------------------------------------------------- 休市日不得產生假結算節點（2026-09-07 勞動節）

class TestHolidayNoSettleNode:
    """2026-09-07 美國勞動節事故：49/56 條鏈被寫進一個與前一交易日等值的假節點。

    ## 怎麼發生的（離線重現過）
    `_feed_chain` 的**已收盤分支**在「`day_d < as_of` ＋ 沒有 nSettle ＋ 鏈上也沒有
    `day_d`」時，會把 `nRef` 當成 `day_d` 當天的結算價寫進鏈。而休市日根本沒有結算價，
    `nRef` 是**前一個交易日**的結算 ⇒ 鏈上多出一個與前一日逐位元組相同的節點
    ⇒ 隔天 `daily = 同值 / 同值 - 1 = +0.00%`，模型再據此寫出「平盤整理」的內文發上 Notion。

    🔴 **不是** `_prev_weekday` 造成的（文件原本記成那樣）。週末之所以沒事，是因為
    交易所根本不回報週末的 `nTradingDay`，不是因為那支函式擋住了。

    ## 判別器：`nRef` 與鏈上最近一筆結算是否相同
    2026-09-07 實測：有 09-07 節點的 56 條裡 **49 條與 09-04 完全相同**（美國線休市），
    **7 條不同**（Brent／橡膠／恆生科技／A50——那天這些交易所有開、有真結算）。
    而正常日「與前一節點等值」的基準率是 0~2%，且那些走的是 nSettle 權威分支、
    根本不會進到這個判斷 ⇒ 誤判成本極低。
    """

    FRI, HOLIDAY, TUE = "2026-09-04", "2026-09-07", "2026-09-08"
    V_THU, V_FRI = 3495.75, 3473.25          # 鋁 ALI2611 真實結算

    def _entry(self):
        return {"active_code": "ALI2611", "chains": {"ALI2611": {"history": {
            "2026-09-03": self.V_THU, self.FRI: self.V_FRI}}}}

    def test_休市日不寫進鏈_並記下沒有結算價(self):
        entry = self._entry()
        q = {"day": 20260907, "settle": 0, "ref": self.V_FRI}   # nRef＝週五結算
        day_d, settle_date, settle_val = dump._feed_chain(
            entry, "ALI2611", q, date(2026, 9, 8))
        ch = entry["chains"]["ALI2611"]
        assert self.HOLIDAY not in ch["history"], \
            f"休市日被寫進鏈了：{ch['history']}"
        assert self.HOLIDAY in ch.get("no_settle", []), "沒有記下『那天沒有結算價』"
        # 本日值要退回鏈上最近一筆真結算，而不是掛在休市日上
        assert settle_date == date(2026, 9, 4) and settle_val == self.V_FRI

    def test_休市隔天不再算出假平盤_而是沿用前一個真實漲跌(self):
        entry = self._entry()
        q = {"day": 20260907, "settle": 0, "ref": self.V_FRI}
        out = dump._chain_changes("aluminum", "ALI2611", q,
                                  date(2026, 9, 8), entry, "LME,ALI2611")
        assert out["daily_pct"] != 0, "又算出假平盤了"
        # 週五對週四的真實漲跌，沿用發佈（與週末的行為一致）
        assert out["daily_pct"] == round((self.V_FRI / self.V_THU - 1) * 100, 4)

    def test_盤中分支不得把假節點造回來(self):
        """修掉已收盤那條還不夠：隔天盤中 `_prev_weekday` 會指回休市日並 setdefault。"""
        entry = self._entry()
        entry["chains"]["ALI2611"]["no_settle"] = [self.HOLIDAY]
        q = {"day": 20260908, "settle": 0, "ref": self.V_FRI}   # day_d >= as_of ⇒ 盤中
        dump._feed_chain(entry, "ALI2611", q, date(2026, 9, 8))
        assert self.HOLIDAY not in entry["chains"]["ALI2611"]["history"], \
            "盤中分支把假節點造回來了"

    def test_國內線也要跳過沒有結算價的日子(self):
        """台指期走 ref_is_prev_day，同樣用 `_prev_weekday` 回推 ⇒ 同樣會踩到。"""
        entry = {"active_code": "TX10AM", "chains": {"TX10AM": {
            "history": {"2026-09-24": 45900.0}, "no_settle": ["2026-09-25"]}}}
        # 09-28（教師節）也休市；快照 day 落在 09-25 這個已知沒有結算價的日子
        q = {"day": 20260928, "settle": None, "ref": 45900.0, "ref_is_prev_day": True}
        dump._feed_chain(entry, "TX10AM", q, date(2026, 9, 29))
        assert "2026-09-25" not in entry["chains"]["TX10AM"]["history"]

    def test_哨兵結算但nRef是新值_仍照舊寫入(self):
        """🔴 回歸守衛：SGX 收盤後會把 nRef 改寫成**當日**結算（橡膠 2026-08-28）。

        那是刻意保留的行為，判別器不可以把它一起關掉——差別正在於 nRef 與鏈上
        最近一筆**不同**。
        """
        entry = {"active_code": "STF2609", "chains": {"STF2609": {"history": {
            "2026-08-25": 235.3, "2026-08-26": 236.3}}}}
        q = {"close": 239.0, "ref": 238.8, "settle": 0, "day": 20260827}
        dump._feed_chain(entry, "STF2609", q, date(2026, 8, 28))
        assert entry["chains"]["STF2609"]["history"]["2026-08-27"] == 238.8
        assert "2026-08-27" not in entry["chains"]["STF2609"].get("no_settle", [])

    def test_鏈是空的時候不可以自作聰明(self):
        """冷啟動沒有可比對的最近值 ⇒ 維持原行為（掛在 day_d），否則海外那條會被改壞。"""
        entry = {"active_code": "STF2609", "chains": {}}
        q = {"close": 239.0, "ref": 238.8, "settle": 0, "day": 20260827}
        dump._feed_chain(entry, "STF2609", q, date(2026, 8, 28))
        assert entry["chains"]["STF2609"]["history"] == {"2026-08-27": 238.8}

    def test_修剪會一起清掉過期的no_settle(self):
        entry = {"active_code": "ALI2611", "chains": {"ALI2611": {
            "history": {"2026-09-04": 3473.25, "2026-07-01": 1.0},
            "no_settle": ["2026-09-07", "2026-07-04"]}}}
        dump._prune_entry(entry, {"ALI2611"}, date(2026, 9, 16))
        ch = entry["chains"]["ALI2611"]
        assert "2026-07-01" not in ch["history"], "舊 history 沒被修剪"
        assert ch["no_settle"] == ["2026-09-07"], f"no_settle 沒被修剪：{ch['no_settle']}"
