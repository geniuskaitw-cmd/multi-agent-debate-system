# 多智能體辯論與決策系統架構 (Multi-Agent Debate & Decision System)

## 1. 系統概述
本系統旨在透過多個具備互斥立場的 AI 智能體（Agents）進行結構化辯論，藉由「提案 $\rightarrow$ 交叉詰問 $\rightarrow$ 修正 $\rightarrow$ 收斂 $\rightarrow$ 獨立評估」的標準化流程，消除單一大型語言模型的思維盲區與幻覺，最終產出具備客觀評分與高度可行性的最佳方案。



---

## 2. 角色定義 (Agent Personas)

本系統由四個核心節點組成，必須在 System Prompt 中嚴格限制其行為邊界：

* **Agent A (創新與利益驅動者)**
    * **立場**：極度樂觀、追求效益最大化、專注於創意與擴張。
    * **職責**：提出具突破性的想法，並在面對質疑時，試圖透過創新手段解決阻力。
* **Agent B (風險控制與事實查核者)**
    * **立場**：極度保守、數據導向、專注於成本控制與邊界風險（紅隊思維）。
    * **職責**：無情地找出提案中的邏輯漏洞、成本盲區與執行困難，並提出防禦性建議。
* **Agent C (總結決策者)**
    * **立場**：絕對中立、具備全局觀、注重落地可行性。
    * **職責**：吸收雙方最終論點（A3, B3），融合出最佳折衷方案（C1）。不參與評分，避免「生成者偏誤」。
* **Agent D (獨立評審委員)**
    * **立場**：冷酷客觀的量化機器。
    * **職責**：接收原始提案背景與最終三個方案（A3, B3, C1），依據預設的量表嚴格打分，並強制輸出 JSON 格式資料。

---

## 3. 核心工作流 (Core Workflow)

系統嚴格按照以下狀態機（State Machine）節點順序執行：

### Phase 1: 提案啟動 (Initiation)
* **Step 1**：使用者輸入原始想法或方案（User Prompt）。
* **Step 2**：系統將輸入平行發送給 Agent A 與 Agent B。

### Phase 2: 初步見解與交叉詰問 (Cross-Examination)
* **Step 3**：A 產出具備創意與利益導向的方案 **A1**；B 產出著重風控與成本檢視的方案 **B1**。
* **Step 4 (第一輪交換)**：
    * 將 B1 傳遞給 A，產出防禦/修正版 **A2**。
    * 將 A1 傳遞給 B，產出風險排查版 **B2**。

### Phase 3: 最終修正 (Final Revision)
* **Step 5 (第二輪交換)**：
    * 將 B2 傳遞給 A，產出最終版 **A3**。
    * 將 A2 傳遞給 B，產出最終版 **B3**。
    *(此階段結束後，A 與 B 的辯論強制終止。)*

### Phase 4: 方案收斂 (Synthesis)
* **Step 6**：系統僅將 **A3** 與 **B3** 傳遞給 Agent C。C 負責融合兩者優點，產出最終最佳化方案 **C1**。

### Phase 5: 獨立評分 (Independent Evaluation)
* **Step 7**：系統將使用者原始問題、**A3**、**B3** 與 **C1** 打包交給 Agent D。
* **Step 8**：Agent D 依據統一維度（創新性、可行性、風險度等）進行獨立評分，並以 `Structured Output (JSON)` 格式回傳。

### Phase 6: 最終輸出 (Final Output)
* **Step 9**：系統將 C1（最佳方案報告）以及 Agent D 的量化評分表呈現給使用者。

---

## 4. 技術棧 (Tech Stack)

此架構需要高度控制流程流向與資料格式，建議採用以下技術組合：

* **核心控制框架**：`LangGraph` (Python)
    * 理由：基於圖論 (Graph) 的狀態機架構，能精準定義節點 (Nodes) 與邊 (Edges)，完美契合本系統的多輪交換與強制中斷邏輯。
* **LLM 模型**：
    * Agent A, B, C：推薦使用 `Claude 3.5 Sonnet` 或 `GPT-4o`，具備強大的長文本推理與角色扮演能力。
    * Agent D：必須支援嚴格的 JSON 輸出（如 OpenAI 的 Structured Outputs 或 Claude 的 Tool Use），確保評分數據格式穩定。
* **資料驗證與結構化**：`Pydantic`
    * 理由：用於定義整個流程中傳遞的 `State` (狀態) 資料結構，以及強制校驗 Agent D 輸出的 JSON 格式是否符合預期。
* **開發環境**：`Python 3.10+`、`Jupyter Notebook` (用於初期單節點測試)。

---

## 5. 開發流程 (Development Flow)

請依照以下步驟順序進行開發，每次對話與測試只專注於一個步驟：

### 步驟一：定義全局狀態 (State Schema)
使用 `TypedDict` 或 `Pydantic` 定義在 LangGraph 中流動的資料結構。包含：
* `user_input` (字串)
* `a_responses` (列表，存放 A1, A2, A3)
* `b_responses` (列表，存放 B1, B2, B3)
* `c_final_plan` (字串，存放 C1)
* `d_scores` (字典/JSON，存放最終評分)

### 步驟二：撰寫角色 Prompt (System Prompts)
分別為 A、B、C、D 四個角色撰寫系統提示詞。重點在於明確告知 A 與 B 它們當下處於第幾輪，以及它們的任務是「提出方案」還是「反駁對方」。

### 步驟三：實作 Agent 節點函數 (Node Functions)
撰寫四個獨立的 Python 函數 (`node_a`, `node_b`, `node_c`, `node_d`)。
* 這些函數負責接收當前的 State，呼叫 LLM API，並將回傳結果更新到 State 中。
* 確保 `node_d` 強制綁定 Pydantic Schema 以輸出 JSON。

### 步驟四：構建圖表拓撲 (Build the Graph)
使用 LangGraph 的 `StateGraph`：
1. 將四個函數加入為節點 (`add_node`)。
2. 定義條件邊界 (`add_conditional_edges`)：設定 A 和 B 互相傳遞資料的迴圈邏輯，並設定當迴圈達到 2 次時，路由轉向 C。
3. 定義線性邊界 (`add_edge`)：設定 C 執行完必定走向 D，D 執行完走向 END。

### 步驟五：編譯與單元測試
編譯圖表 (`graph.compile()`)，先輸入一個簡單的測試命題，觀察終端機中 State 的變化過程，確認迴圈是否正確中斷，且 JSON 解析沒有報錯。