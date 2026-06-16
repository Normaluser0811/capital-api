# 海外選擇權 symbol 格式規格（人工依 field_survey capture 填寫）

> 來源：scripts/spike_overseas_options.py 的 docs/overseas_options_field_survey.md。
> 這份是 Phase 3 `symbol_parser.py` 的依據；**填妥並 PASS 才進 Phase 2+。**

## 1. symbol 拆解規則

| 區段 | 範例字元 | 含義 | 備註 |
|---|---|---|---|
| root | | 商品代碼 | 對照 margin_root_xref → contract_specs.root |
| 到期 | | 年月 / 合約月碼 | |
| 履約價 | | strike | 是否含 divisor？ |
| 買賣權 | | C / P | 編碼位置 |

範例：`<填一個實際 symbol> = <逐段標註>`

## 2. 到期日(LTD) 來源

- [ ] 群益是否回傳到期/合約日原生欄位？欄位名＝______
- [ ] 若否：用哪個規則推 LTD（交易所行事曆 / contract_specs.ltd_rule）？

## 3. 標的期貨對應（Black-76 的 F）

- 選擇權 root → 取哪個到期月期貨當 F：______

## 4. 訂閱 / 連線限制

- 單帳號訂閱檔數上限：______
- 報價更新頻率 → 建議 flush 秒數：______

## 5. PASS 判定

- [ ] symbol 可確定性拆解
- [ ] 選定 MVP 標的 root 已知且已對映 contract_specs
- [ ] 到期日來源已定
- [ ] flush 秒數有依據
