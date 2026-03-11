# 實作計畫：多智能體辯論與決策系統

## 概述

依據設計文件，以增量方式建構多智能體辯論系統。從環境設定與資料模型開始，逐步實作智能體節點、LangGraph 狀態機、API 路由，最後完成前端介面與整合。每個步驟皆建立在前一步驟之上，確保無孤立程式碼。

## 任務

- [x] 1. 建立環境設定與資料模型
  - [x] 1.1 建立 `config.py` 環境設定模組
    - 使用 `pydantic-settings` 的 `BaseSettings` 定義 `Settings` 類別
    - 包含 `google_api_key`、`agent_a_model`、`agent_b_model`、`agent_c_model`、`agent_d_model`、`llm_timeout`、`llm_max_retries` 欄位
    - 設定預設模型名稱（Agent A/B/C: `gemini-3-flash-preview`、Agent D: `gemini-3.1-pro-preview`）
    - 實作 `get_settings()` 函數，缺少必要設定時拋出明確錯誤
    - 建立 `.env.example` 範例檔案
    - _需求: 18.1, 18.2, 18.3, 18.4_

  - [ ]* 1.2 撰寫 `config.py` 的屬性測試
    - **Property 11: 缺少 API 金鑰時啟動失敗**
    - **驗證: 需求 18.4**

  - [x] 1.3 建立 `models.py` 資料模型模組
    - 定義 `DebatePhase` 列舉（INITIATED, PHASE_1~5, COMPLETED, FAILED）
    - 定義 `DimensionScore`、`ProposalScore`、`ScoreCard` 評分模型
    - 定義 `DebateState` 辯論狀態模型（含 session_id、user_input、a1~a3、b1~b3、c1、scores、current_phase、errors）
    - 定義 API 請求/回應模型：`DebateCreateRequest`（含空白驗證）、`DebateCreateResponse`、`DebateStatusResponse`、`PhaseUpdate`
    - _需求: 8.1, 8.2, 1.3, 5.2, 5.3, 5.4_

  - [ ]* 1.4 撰寫資料模型的屬性測試
    - **Property 1: 會話識別碼唯一性** — 驗證: 需求 1.1
    - **Property 2: 空白輸入拒絕** — 驗證: 需求 1.3
    - **Property 6: 評分表結構與範圍驗證** — 驗證: 需求 5.2, 5.3
    - **Property 7: 評分表 JSON 序列化往返** — 驗證: 需求 5.4
    - **Property 9: 推薦方案與最高分一致** — 驗證: 需求 6.4, 14.4, 13.4

- [x] 2. 檢查點 — 確認所有測試通過
  - 確認所有測試通過，如有疑問請詢問使用者。

- [x] 3. 實作提示詞模組與智能體節點
  - [x] 3.1 建立 `prompts.py` 提示詞模組
    - 實作 `get_agent_a_prompt(phase: int)` — 創新驅動者，極度樂觀、追求效益最大化
    - 實作 `get_agent_b_prompt(phase: int)` — 風險控制者，極度保守、數據導向
    - 實作 `get_agent_c_prompt()` — 總結決策者，絕對中立、注重落地可行性
    - 實作 `get_agent_d_prompt()` — 獨立評審，冷酷客觀、強制 JSON 格式輸出（含 ScoreCard JSON Schema）
    - _需求: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 3.2 建立 `agents.py` 智能體節點模組
    - 實作 `call_llm_with_retry()` — 含指數退避重試邏輯（2^attempt + 隨機抖動）、120 秒逾時、JSON 模式支援
    - 定義自訂例外 `LLMCallError`
    - 實作 `node_a(state)` — 根據 current_phase 產出 A1/A2/A3
    - 實作 `node_b(state)` — 根據 current_phase 產出 B1/B2/B3
    - 實作 `node_c(state)` — 接收 A3、B3 產出 C1
    - 實作 `node_d(state)` — 接收所有方案，產出 JSON 評分表，含 ScoreCard 驗證與重試
    - _需求: 2.1, 2.2, 3.1, 3.2, 4.1, 4.2, 5.1, 5.2, 5.4, 5.5, 5.6, 17.1, 17.2, 17.4_

  - [ ]* 3.3 撰寫智能體模組的屬性測試
    - **Property 3: 智能體產出寫入狀態** — 驗證: 需求 2.4, 3.4, 1.4, 8.2
    - **Property 8: 指數退避重試行為** — 驗證: 需求 5.5, 8.3, 17.1, 17.2

- [x] 4. 建構 LangGraph 狀態機
  - [x] 4.1 建立 `graph.py` 狀態機模組
    - 使用 `StateGraph(DebateState)` 建構辯論流程圖
    - 加入 `node_a`、`node_b`、`node_c`、`node_d` 四個節點
    - Phase 1~3 使用 LangGraph 平行分支執行 Agent A 與 Agent B
    - 實作 `phase_router(state)` 條件路由函數
    - 定義節點間的邊，確保 Phase 1→2→3→4→5→COMPLETED 順序
    - 編譯圖表為可執行工作流實例
    - _需求: 10.1, 10.2, 10.3, 10.4, 2.3, 3.3, 4.4_

  - [ ]* 4.2 撰寫狀態機的屬性測試
    - **Property 4: 辯論階段單調遞進** — 驗證: 需求 8.4, 10.2
    - **Property 5: Phase 3 後辯論循環終止** — 驗證: 需求 4.3

- [x] 5. 檢查點 — 確認所有測試通過
  - 確認所有測試通過，如有疑問請詢問使用者。

- [x] 6. 實作 API 路由與 SSE
  - [x] 6.1 建立 `api.py` API 路由模組
    - 實作 `POST /debates` — 驗證輸入、建立 DebateState、產生 session_id、啟動背景辯論任務
    - 實作 `GET /debates/{session_id}` — 查詢辯論狀態，不存在時回傳 404
    - 實作 `GET /debates/{session_id}/stream` — SSE 端點，推送 phase_start、phase_complete、debate_complete、error 事件
    - 使用記憶體字典儲存辯論會話狀態
    - _需求: 15.1, 15.2, 15.3, 15.4, 15.5, 1.1, 1.2, 1.3_

  - [x] 6.2 建立 `main.py` FastAPI 應用入口
    - 建立 FastAPI 應用實例
    - 掛載 API 路由
    - 掛載靜態檔案目錄（`static/`）
    - 啟動時驗證環境設定
    - _需求: 15.5, 18.4_

  - [ ]* 6.3 撰寫 API 端點的屬性測試
    - **Property 10: 不存在的會話回傳 404** — 驗證: 需求 15.4

- [x] 7. 檢查點 — 確認所有測試通過
  - 確認所有測試通過，如有疑問請詢問使用者。

- [x] 8. 實作前端介面
  - [x] 8.1 建立 `static/index.html` 前端單頁應用 — 輸入區域與辯論時間軸
    - 建立深色主題基底（背景 `#0F172A`、卡片 `#1E293B`）
    - 實作多行文字輸入區域與「啟動辯論」按鈕
    - 點擊後停用輸入區域與按鈕，防止重複提交
    - 使用翡翠綠 `#10B981` 與琥珀金 `#F59E0B` 作為強調色，禁止藍紫漸變
    - 實作六階段辯論時間軸，含進行中動畫與已完成狀態
    - 透過 SSE 接收即時狀態更新，連線中斷時顯示提示與重新連線選項
    - 為所有互動元素提供 ARIA 標籤，支援鍵盤導航
    - _需求: 11.1, 11.2, 11.3, 11.4, 11.5, 12.1, 12.2, 12.3, 12.4, 12.5, 16.3, 16.4, 16.5_

  - [x] 8.2 實作前端方案對比與評分視覺化
    - 實作三欄並排方案對比檢視（A3/B3/C1），以不同顏色標記各智能體
    - 支援切換為單欄逐一檢視模式
    - 每個方案卡片顯示 Agent D 對該方案的總分
    - 使用 Chart.js 繪製雷達圖，三個方案以不同顏色呈現
    - 實作評分表格，顯示各維度分數與評語
    - 標示綜合推薦度最高的方案為「推薦方案」
    - 標示各方案的最高分與最低分維度
    - 實作響應式佈局：桌面三欄、平板/手機（<768px）單欄堆疊
    - _需求: 7.1, 7.2, 7.3, 7.4, 13.1, 13.2, 13.3, 13.4, 14.1, 14.2, 14.3, 14.4, 16.1, 16.2_

- [x] 9. 最終檢查點 — 確認所有測試通過
  - 確認所有測試通過，如有疑問請詢問使用者。

## 備註

- 標記 `*` 的任務為選擇性任務，可跳過以加速 MVP 開發
- 每個任務皆標註對應的需求編號，確保可追溯性
- 屬性測試驗證通用正確性屬性，單元測試驗證具體場景與邊界案例
- 所有 LLM 呼叫在測試中使用 mock，不實際呼叫外部 API
