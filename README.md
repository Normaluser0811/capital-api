# Capital API

群益期貨 API Python 封裝套件

## 功能特色

- 簡化的登入/登出管理
- 即時報價訂閱 (股票、期貨)
- **選擇權報價** (履約價、Bid/Ask、成交價)
- **選擇權鏈資料結構** (方便建立視覺化儀表板)
- 委託/成交回報查詢
- 完整的型別提示

## 系統需求

- **Windows** (COM 元件僅支援 Windows)
- Python 3.10+
- 群益 API 元件 (SKCOM.dll)

## 安裝

### 1. 安裝群益 API 元件

1. 向群益期貨申請 API 使用權限
2. 下載並安裝群益 API 元件
3. 確認 `SKCOM.dll` 已正確註冊

### 2. 安裝本套件

```bash
cd capital-api
pip install -e .
```

## 快速開始

### 登入

```python
from capitalapi import CapitalClient
from capitalapi.constants import Environment

# 建立客戶端
client = CapitalClient(environment=Environment.TEST)

# 登入
client.login("YOUR_ID", "YOUR_PASSWORD")

# 取得帳號資訊
for account in client.accounts:
    print(f"帳號: {account.full_account}")

# 登出
client.logout()
```

### 即時報價 (股票/期貨)

```python
from capitalapi import CapitalClient, QuoteManager
from capitalapi.quote import StockQuote

client = CapitalClient()
client.login("YOUR_ID", "YOUR_PASSWORD")

# 建立報價管理器
quote = QuoteManager(client)

# 設定報價回調
def on_quote(q: StockQuote):
    print(f"{q.stock_no}: {q.close_price}")

quote.on_quote = on_quote

# 連線並訂閱
quote.connect()
quote.subscribe("2330")  # 台積電

# 記得要處理 Windows 訊息迴圈
import pythoncom
import time
while True:
    pythoncom.PumpWaitingMessages()
    time.sleep(0.1)
```

### 選擇權報價

```python
from capitalapi import CapitalClient, OptionsQuoteManager, OptionQuote

client = CapitalClient()
client.login("YOUR_ID", "YOUR_PASSWORD")

# 建立選擇權報價管理器
options = OptionsQuoteManager(client)

# 設定報價回調
def on_option_quote(q: OptionQuote):
    type_str = "Call" if q.is_call() else "Put"
    print(
        f"[{type_str}] 履約價={q.strike_price:.0f} "
        f"成交={q.close_price:.2f} "
        f"Bid={q.bid_price:.2f} Ask={q.ask_price:.2f}"
    )

options.on_quote = on_option_quote

# 連線並訂閱
options.connect()
options.subscribe_many([
    "TXO22000C4",  # 台指選 22000 Call
    "TXO22000P4",  # 台指選 22000 Put
])

# 取得選擇權鏈
chain = options.get_chain("TXO")
for strike in chain.get_sorted_strikes():
    call = chain.strikes[strike].call
    put = chain.strikes[strike].put
    print(f"履約價 {strike}: Call={call}, Put={put}")
```

### 選擇權報價欄位

`OptionQuote` 包含以下欄位：

| 欄位 | 說明 |
|------|------|
| `strike_price` | 履約價 |
| `close_price` | 成交價 |
| `bid_price` | 買價 (Bid) |
| `ask_price` | 賣價 (Ask) |
| `bid_qty` | 買量 |
| `ask_qty` | 賣量 |
| `mid_price` | 買賣中價 (計算屬性) |
| `spread` | 買賣價差 (計算屬性) |
| `option_type` | Call/Put |
| `volume` | 成交量 |

## 專案結構

```
capital-api/
├── src/capitalapi/
│   ├── __init__.py       # 主要匯出
│   ├── client.py         # 登入管理
│   ├── quote.py          # 股票/期貨報價
│   ├── options_quote.py  # 選擇權報價
│   ├── options_chain.py  # 選擇權鏈結構
│   ├── order.py          # 下單功能 (預留)
│   ├── constants.py      # 常數定義
│   ├── exceptions.py     # 例外定義
│   └── skcom.py          # COM 元件封裝
├── examples/             # 範例程式
│   ├── 01_login.py
│   ├── 02_quote.py
│   ├── 03_order_query.py
│   ├── 04_options_quote.py
│   └── 05_options_chain.py
├── tests/
├── pyproject.toml
└── README.md
```

## 注意事項

1. **僅支援 Windows**: 群益 API 使用 COM 元件，僅能在 Windows 運行
2. **需要憑證**: 下單功能需要先讀取憑證
3. **訊息迴圈**: 使用報價功能時需要處理 Windows 訊息迴圈
4. **商品代號格式**: 選擇權代號格式需參考群益 API 文件

## 相關資源

- [群益期貨 API 官方文件](https://www.capital.com.tw/)
- [twmarket](../tw-market-data/) - 台灣股市參考資料套件

## License

MIT
