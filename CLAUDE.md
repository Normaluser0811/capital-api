# Claude Code 工作規範

**最後更新**: 2026-01-18
**專案版本**: v0.1.0
**專案狀態**: 初始開發

---

## 專案概述

`capital-api` 是群益期貨 API 的 Python 封裝套件，提供：
- **登入/登出管理** - 簡化的認證流程
- **即時報價訂閱** - 台股、期貨報價
- **下單功能** - 委託/成交查詢
- **型別提示** - 完整的 Type Hints

### 專案關係

```
PythonProjects/
├── capital-api/         # 本專案 (群益 API 封裝)
├── tw-market-data/      # 台股參考資料 (可選依賴)
├── scraper/             # PDF 爬蟲
└── financialreport/     # 報告處理
```

### 技術限制

- **僅支援 Windows** (COM 元件)
- 需要安裝群益 API 元件 (SKCOM.dll)
- Python 3.10+

---

## 任務執行流程

### 1. 執行任務前 - 必須先建立 Todo List

在開始任何任務之前，**必須**先執行以下步驟：

1. **分析任務需求**：理解使用者的需求和目標
2. **建立 Todo List**：使用 `TodoWrite` 工具列出所有需要完成的項目
3. **拆解細項**：將大任務拆解成可執行的小步驟 (Todo Items)
4. **確認優先順序**：按照依賴關係和重要性排序

### 2. 執行任務中 - 持續更新狀態

- 開始執行某項任務時，將該項標記為 `in_progress`
- 完成某項任務後，**立即**標記為 `completed`
- 發現新的子任務時，即時加入 Todo List

### 3. 完成任務後 - 更新文件

任務完成後，**必須**更新以下文件：

| 文件 | 更新時機 | 內容 |
|------|----------|------|
| `README.md` | 新增功能/重大變更 | 功能說明、使用方式 |
| `TODO.md` | 任務完成/新增 | 待辦事項清單 |
| `CLAUDE.md` | 工作規範變更 | 更新工作規範 |

---

## 專案結構

```
capital-api/
├── src/capitalapi/         # 核心套件
│   ├── __init__.py         # API 匯出
│   ├── client.py           # 登入管理 (CapitalClient)
│   ├── quote.py            # 報價功能 (QuoteManager)
│   ├── order.py            # 下單功能 (OrderManager)
│   ├── constants.py        # 常數定義
│   ├── exceptions.py       # 例外定義
│   └── skcom.py            # COM 元件封裝
│
├── examples/               # 範例程式
│   ├── 01_login.py         # 登入範例
│   ├── 02_quote.py         # 報價範例
│   └── 03_order_query.py   # 查詢範例
│
├── tests/                  # 測試
├── .vscode/                # VSCode 設定
├── pyproject.toml          # 專案配置
├── README.md               # 專案說明
├── TODO.md                 # 待辦事項
└── CLAUDE.md               # 本文件
```

---

## 核心模組說明

### CapitalClient (client.py)
主要客戶端，負責：
- 登入/登出
- 環境設定 (正式/測試)
- 帳號管理
- 憑證讀取

### QuoteManager (quote.py)
報價管理，負責：
- 連線報價伺服器
- 訂閱/取消訂閱股票
- 報價事件回調

### OrderManager (order.py)
下單管理，負責：
- 下單解鎖
- 委託回報查詢
- 成交回報查詢

---

## 代碼風格

- Python: 遵循 PEP 8
- 使用 Type Hints
- 必要時添加 docstring
- 保持函數簡潔，單一職責
- 使用 dataclass 定義資料結構

## 提交規範

```
<type>: <description>

type: feat | fix | docs | refactor | test | chore
```

---

## 相關資源

- [群益期貨 API 官方文件](https://www.capital.com.tw/)
- [tw-market-data](../tw-market-data/) - 台灣股市參考資料套件
- API 範例程式: `E:\CapitalFuturesAPI\`

---

**維護者**: Claude Code
**最後更新**: 2026-01-18
