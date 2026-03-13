# Requirements Document

## Introduction

本功能為現有的多智能體辯論與決策系統新增兩項核心能力：(1) 以 SQLite 取代記憶體內 dict 儲存，使辯論結果在伺服器重啟後仍然保留；(2) 新增使用者帳號密碼登入機制搭配 JWT 權杖，讓多位使用者各自管理自己的辯論歷史。前端同步新增登入/註冊介面與歷史紀錄面板，所有 UI 文字維持繁體中文，不使用 emoji，深色主題與現有設計一致。

## Glossary

- **Debate_System**: 現有的多智能體辯論與決策系統後端（FastAPI 應用程式）
- **Frontend**: 位於 `static/index.html` 的單頁前端應用程式（vanilla JS）
- **Database**: 位於 `/app/data/debates.db`（Docker 容器內）的 SQLite 單檔資料庫，透過 aiosqlite 進行非同步存取
- **Users_Table**: SQLite 中儲存使用者帳號資訊的資料表，包含 username 與 bcrypt 雜湊密碼
- **Debates_Table**: SQLite 中儲存辯論紀錄的資料表，包含 session_id、user_id、user_input、config、a_responses、b_responses、c1、scores、phase、timestamps 等欄位，部分欄位以 JSON 格式儲存
- **JWT**: JSON Web Token，用於驗證已登入使用者身分的權杖
- **Auth_Router**: 處理使用者註冊與登入的 API 路由模組
- **History_Panel**: 前端中顯示使用者過往辯論紀錄的側邊面板或 Modal

## Requirements

### Requirement 1: SQLite 資料庫初始化

**User Story:** 身為系統管理者，我希望系統啟動時自動建立 SQLite 資料庫與所需資料表，以便無需手動設定即可開始使用。

#### Acceptance Criteria

1. WHEN the Debate_System starts, THE Database SHALL create the `users` table with columns: id (INTEGER PRIMARY KEY), username (TEXT UNIQUE NOT NULL), password_hash (TEXT NOT NULL), created_at (TEXT NOT NULL)
2. WHEN the Debate_System starts, THE Database SHALL create the `debates` table with columns: session_id (TEXT PRIMARY KEY), user_id (INTEGER NOT NULL REFERENCES users(id)), user_input (TEXT NOT NULL), config (TEXT NOT NULL), a_responses (TEXT NOT NULL), b_responses (TEXT NOT NULL), c1 (TEXT), scores (TEXT), phase (TEXT NOT NULL), created_at (TEXT NOT NULL), updated_at (TEXT NOT NULL)
3. WHEN the database file does not exist at the configured path, THE Database SHALL create a new SQLite file at `/app/data/debates.db`
4. WHEN the database file already exists, THE Database SHALL reuse the existing file without data loss
5. IF the database directory does not exist, THEN THE Debate_System SHALL create the directory before initializing the database

### Requirement 2: Docker Volume 持久化

**User Story:** 身為系統管理者，我希望資料庫檔案透過 Docker volume mount 保存在主機上，以便容器重建後資料仍然存在。

#### Acceptance Criteria

1. THE Debate_System SHALL store the SQLite database file at the path specified by the `DATABASE_PATH` environment variable, defaulting to `/app/data/debates.db`
2. THE Docker configuration SHALL mount the host directory `./data` to the container path `/app/data` as a volume
3. WHEN the Docker container is rebuilt and restarted, THE Database SHALL retain all previously stored users and debates data

### Requirement 3: 使用者註冊

**User Story:** 身為新使用者，我希望能以帳號密碼註冊帳號，以便開始使用辯論系統。

#### Acceptance Criteria

1. WHEN a registration request with a valid username and password is received at `POST /auth/register`, THE Auth_Router SHALL create a new user record in the Users_Table with the password stored as a bcrypt hash
2. WHEN a registration request contains a username that already exists in the Users_Table, THE Auth_Router SHALL return HTTP 409 with an error message indicating the username is taken
3. WHEN a registration request contains a username shorter than 3 characters or longer than 32 characters, THE Auth_Router SHALL return HTTP 422 with a validation error
4. WHEN a registration request contains a password shorter than 6 characters, THE Auth_Router SHALL return HTTP 422 with a validation error
5. WHEN registration succeeds, THE Auth_Router SHALL return HTTP 201 with a JSON body containing the username and a success message

### Requirement 4: 使用者登入與 JWT 簽發

**User Story:** 身為已註冊使用者，我希望能以帳號密碼登入並取得 JWT 權杖，以便存取受保護的 API。

#### Acceptance Criteria

1. WHEN a login request with valid credentials is received at `POST /auth/login`, THE Auth_Router SHALL return HTTP 200 with a JSON body containing an `access_token` field (JWT) and a `token_type` field set to `bearer`
2. WHEN a login request contains an incorrect username or password, THE Auth_Router SHALL return HTTP 401 with an error message indicating invalid credentials
3. THE Auth_Router SHALL sign the JWT using a secret key loaded from the `JWT_SECRET` environment variable with the HS256 algorithm
4. THE Auth_Router SHALL include the user's id and username in the JWT payload as `sub` and `username` claims
5. THE Auth_Router SHALL set the JWT expiration time to 24 hours from the time of issuance

### Requirement 5: API 端點認證保護

**User Story:** 身為系統管理者，我希望所有辯論相關 API 端點都需要有效的 JWT 才能存取，以便確保資料隔離。

#### Acceptance Criteria

1. WHEN a request to `POST /debates`, `GET /debates/{session_id}`, `GET /debates/{session_id}/stream`, `GET /debates`, or `DELETE /debates/{session_id}` lacks a valid JWT in the `Authorization: Bearer <token>` header, THE Debate_System SHALL return HTTP 401
2. WHEN a request contains an expired JWT, THE Debate_System SHALL return HTTP 401 with an error message indicating the token has expired
3. WHEN a request contains a JWT with an invalid signature, THE Debate_System SHALL return HTTP 401
4. THE Debate_System SHALL extract the authenticated user's id from the JWT and use the id to scope all database queries to that user's data
5. THE `GET /settings/defaults` endpoint SHALL remain accessible without authentication

### Requirement 6: 辯論結果持久化至 SQLite

**User Story:** 身為使用者，我希望辯論結果儲存在資料庫中，以便伺服器重啟後仍可查閱過往辯論。

#### Acceptance Criteria

1. WHEN a new debate is created via `POST /debates`, THE Debate_System SHALL insert a new row into the Debates_Table with the authenticated user's id, user_input, config (as JSON), empty a_responses and b_responses arrays (as JSON), phase set to `initiated`, and current timestamps
2. WHEN a debate round completes, THE Debate_System SHALL update the corresponding row in the Debates_Table with the latest a_responses and b_responses arrays (as JSON) and the current phase
3. WHEN the synthesis phase completes, THE Debate_System SHALL update the c1 column in the Debates_Table
4. WHEN the scoring phase completes, THE Debate_System SHALL update the scores column (as JSON) and set the phase to `completed` in the Debates_Table
5. IF the debate pipeline fails, THEN THE Debate_System SHALL update the phase to `failed` in the Debates_Table
6. THE Debate_System SHALL maintain the in-memory DebateState dict for active SSE streaming, and persist state changes to the Database at each phase transition


### Requirement 7: 辯論歷史列表 API

**User Story:** 身為使用者，我希望能查詢自己的辯論歷史列表（含分頁），以便快速瀏覽過往辯論。

#### Acceptance Criteria

1. WHEN an authenticated request is received at `GET /debates`, THE Debate_System SHALL return a paginated list of the authenticated user's debates, ordered by created_at descending
2. THE Debate_System SHALL accept optional query parameters `page` (default 1, minimum 1) and `page_size` (default 20, minimum 1, maximum 100) for pagination
3. THE Debate_System SHALL return each debate item with the fields: session_id, user_input (first 50 characters), phase, created_at, updated_at
4. THE Debate_System SHALL include `total`, `page`, `page_size`, and `total_pages` fields in the response for pagination metadata

### Requirement 8: 辯論刪除 API

**User Story:** 身為使用者，我希望能刪除自己的辯論紀錄，以便管理個人資料。

#### Acceptance Criteria

1. WHEN an authenticated request is received at `DELETE /debates/{session_id}`, THE Debate_System SHALL delete the debate record from the Debates_Table if the debate belongs to the authenticated user
2. WHEN the specified session_id does not exist in the Debates_Table, THE Debate_System SHALL return HTTP 404
3. WHEN the specified debate belongs to a different user, THE Debate_System SHALL return HTTP 403
4. WHEN deletion succeeds, THE Debate_System SHALL return HTTP 200 with a confirmation message

### Requirement 9: 前端登入與註冊介面

**User Story:** 身為使用者，我希望在進入應用程式前看到登入/註冊介面，以便驗證身分。

#### Acceptance Criteria

1. WHEN the Frontend loads and no valid JWT exists in localStorage, THE Frontend SHALL display a login/register modal covering the entire viewport
2. THE Frontend SHALL provide a form with username and password fields, and two action buttons: one for login and one for registration
3. WHEN the user submits valid credentials for login, THE Frontend SHALL call `POST /auth/login`, store the returned JWT in localStorage under the key `token`, and dismiss the modal to reveal the main application
4. WHEN the user submits valid credentials for registration, THE Frontend SHALL call `POST /auth/register`, and upon success display a confirmation message prompting the user to log in
5. WHEN the login or registration API returns an error, THE Frontend SHALL display the error message within the modal without navigating away
6. THE Frontend SHALL render all login/register UI text in Traditional Chinese without emoji
7. THE Frontend SHALL style the login/register modal consistent with the existing dark theme (background #0F172A, card background #131825, border color #1E2A3A, accent color #10B981)

### Requirement 10: JWT 管理與自動登出

**User Story:** 身為使用者，我希望系統在 JWT 過期時自動導向登入畫面，以便重新驗證身分。

#### Acceptance Criteria

1. THE Frontend SHALL include the JWT from localStorage in the `Authorization: Bearer <token>` header for all API requests to protected endpoints
2. WHEN any API request returns HTTP 401, THE Frontend SHALL remove the JWT from localStorage and display the login modal
3. THE Frontend SHALL provide a logout function that removes the JWT from localStorage and displays the login modal
4. WHEN the user clicks a logout button in the header area, THE Frontend SHALL invoke the logout function

### Requirement 11: 前端歷史紀錄面板

**User Story:** 身為使用者，我希望在介面上有一個歷史紀錄面板，以便瀏覽和載入過往辯論結果。

#### Acceptance Criteria

1. THE Frontend SHALL display a "HISTORY" button in the header area, positioned next to the existing settings gear button
2. WHEN the user clicks the HISTORY button, THE Frontend SHALL open a side panel or modal displaying the user's debate history fetched from `GET /debates`
3. THE Frontend SHALL display each history item with: user_input summary (first 50 characters), created_at timestamp, and phase status displayed as one of "completed", "in-progress", or "failed"
4. WHEN the user clicks a history item, THE Frontend SHALL fetch the full debate data from `GET /debates/{session_id}` and render the complete result (proposals, scoring, pipeline) in the main view
5. THE Frontend SHALL display a delete button on each history item that calls `DELETE /debates/{session_id}` and removes the item from the list upon success
6. THE Frontend SHALL support pagination in the history panel, loading additional pages when the user scrolls or clicks a "load more" control
7. THE Frontend SHALL render all history panel UI text in Traditional Chinese without emoji
8. THE Frontend SHALL style the history panel consistent with the existing dark theme

### Requirement 12: 現有辯論流程相容性

**User Story:** 身為使用者，我希望現有的辯論流程（SSE 串流、Pipeline 視覺化、評分）在新增功能後維持不變。

#### Acceptance Criteria

1. THE Debate_System SHALL continue to support the existing SSE streaming mechanism at `GET /debates/{session_id}/stream` with the same event types: round_start, round_complete, synthesis_start, scoring_start, debate_complete, error
2. THE Debate_System SHALL continue to return the same DebateStatusResponse schema from `GET /debates/{session_id}` including all fields: session_id, current_phase, current_round, total_rounds, user_input, a_responses, b_responses, c1, scores, errors
3. THE Frontend SHALL continue to render the pipeline visualization, proposal cards, radar chart, and score table identically to the current implementation after a debate completes
4. THE Debate_System SHALL continue to support custom agent prompts and configurable round counts via the DebateConfig model
