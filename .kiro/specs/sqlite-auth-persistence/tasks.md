# Implementation Plan: SQLite Auth Persistence

## Overview

將現有多智能體辯論系統從記憶體內 dict 儲存遷移至 SQLite 持久化，並新增 JWT 認證機制與前端登入/歷史面板。實作以新模組（`database.py`、`auth.py`）為主，最小化對現有程式碼的修改。辯論流程（SSE 串流、Pipeline、評分）維持完全相容。

## Tasks

- [x] 1. Set up dependencies and configuration
  - [x] 1.1 Update `requirements.txt` to add `aiosqlite`, `bcrypt`, `PyJWT`
    - Append `aiosqlite>=0.20.0`, `bcrypt>=4.0.0`, `PyJWT>=2.8.0` to `requirements.txt`
    - _Requirements: 1.1, 4.3_

  - [x] 1.2 Add new settings fields to `config.py`
    - Add `database_path: str = "/app/data/debates.db"` to `Settings`
    - Add `jwt_secret: str` (required, no default) to `Settings`
    - Add `jwt_expire_hours: int = 24` to `Settings`
    - _Requirements: 2.1, 4.3, 4.5_

  - [x] 1.3 Add auth and pagination Pydantic models to `models.py`
    - Add `RegisterRequest(username: str Field(min_length=3, max_length=32), password: str Field(min_length=6))`
    - Add `RegisterResponse(username: str, message: str)`
    - Add `LoginRequest(username: str, password: str)`
    - Add `TokenResponse(access_token: str, token_type: str = "bearer")`
    - Add `DebateListItem(session_id, user_input, phase, created_at, updated_at)`
    - Add `PaginatedDebateList(items, total, page, page_size, total_pages)`
    - _Requirements: 3.1, 3.3, 3.4, 4.1, 7.3, 7.4_

  - [x] 1.4 Update Docker configuration for volume persistence
    - Add `RUN mkdir -p /app/data` to `Dockerfile`
    - Add `volumes: ["./data:/app/data"]` to `docker-compose.yml` under the `debate` service
    - Add `JWT_SECRET` environment variable reference in docker-compose or .env documentation
    - _Requirements: 2.2, 2.3_

- [x] 2. Implement database layer (`database.py`)
  - [x] 2.1 Create `database.py` with `init_db()` and `get_db()` functions
    - Implement `init_db()`: create database directory if not exists, open aiosqlite connection, execute `CREATE TABLE IF NOT EXISTS` for `users` and `debates` tables with exact schema from design (including indexes `idx_debates_user_id` and `idx_debates_created_at`)
    - Implement `get_db()` as an async generator for FastAPI dependency injection, yielding an aiosqlite connection with `row_factory = aiosqlite.Row`
    - Use `DATABASE_PATH` from `config.get_settings()`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1_

  - [x] 2.2 Implement user CRUD functions in `database.py`
    - Implement `create_user(db, username, password_hash) -> int`: INSERT into users, return lastrowid; raise IntegrityError on duplicate username
    - Implement `get_user_by_username(db, username) -> dict | None`: SELECT from users, return dict with id, username, password_hash, created_at or None
    - _Requirements: 3.1, 4.1_

  - [x] 2.3 Implement debate CRUD functions in `database.py`
    - Implement `insert_debate(db, session_id, user_id, user_input, config_json)`: INSERT with phase='initiated', empty JSON arrays for a_responses/b_responses, current timestamps
    - Implement `update_debate(db, session_id, **kwargs)`: UPDATE any combination of a_responses, b_responses, c1, scores, phase, updated_at
    - Implement `get_debate(db, session_id) -> dict | None`: SELECT full row by session_id
    - Implement `list_debates(db, user_id, page, page_size) -> tuple[list[dict], int]`: paginated query ordered by created_at DESC, user_input truncated to 50 chars, return (items, total_count)
    - Implement `delete_debate(db, session_id)`: DELETE by session_id
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 8.1_

  - [ ]* 2.4 Write property tests for database layer
    - **Property 8: Debate creation persists to database** — For any valid debate creation, verify the row exists with correct user_id, user_input, config, empty arrays, phase='initiated', and non-null timestamps
    - **Validates: Requirements 6.1**

  - [ ]* 2.5 Write property test for pagination
    - **Property 10: Debate list is paginated and ordered** — For any user with N debates, verify GET returns at most page_size items ordered by created_at DESC with correct pagination metadata (total, page, page_size, total_pages)
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4**

- [x] 3. Implement authentication module (`auth.py`)
  - [x] 3.1 Create `auth.py` with JWT utility functions
    - Implement `create_access_token(user_id, username) -> str`: sign JWT with HS256 using `JWT_SECRET`, payload contains `sub=user_id`, `username`, `exp` (24h from now), `iat`
    - Implement `get_current_user(authorization, db) -> dict`: parse `Authorization: Bearer <token>` header, decode JWT, return `{id, username}`; raise HTTPException(401) for missing/invalid/expired tokens with appropriate Chinese error messages
    - _Requirements: 4.3, 4.4, 4.5, 5.1, 5.2, 5.3_

  - [x] 3.2 Implement registration endpoint in `auth.py`
    - Create `auth_router = APIRouter(prefix="/auth", tags=["auth"])`
    - Implement `POST /auth/register`: validate input (Pydantic handles 422), check duplicate username (409), hash password with bcrypt, create user, return 201 with `{username, message}`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 3.3 Implement login endpoint in `auth.py`
    - Implement `POST /auth/login`: look up user by username, verify password with bcrypt, return `{access_token, token_type: "bearer"}` on success, 401 on failure
    - _Requirements: 4.1, 4.2_

  - [ ]* 3.4 Write property tests for registration
    - **Property 1: Registration creates bcrypt-hashed user** — For any valid username (3-32 chars) and password (6+ chars), verify 201 response and stored password_hash verifies against original password
    - **Validates: Requirements 3.1, 3.5**

  - [ ]* 3.5 Write property test for duplicate username rejection
    - **Property 2: Duplicate username registration is rejected** — For any existing username, verify subsequent registration returns 409
    - **Validates: Requirements 3.2**

  - [ ]* 3.6 Write property test for invalid registration inputs
    - **Property 3: Invalid registration inputs are rejected** — For any username <3 or >32 chars, or password <6 chars, verify 422 and no user created
    - **Validates: Requirements 3.3, 3.4**

  - [ ]* 3.7 Write property test for login JWT
    - **Property 4: Login returns well-formed JWT** — For any registered user, verify login returns JWT decodable with JWT_SECRET/HS256, containing correct sub/username/exp claims
    - **Validates: Requirements 4.1, 4.3, 4.4, 4.5**

  - [ ]* 3.8 Write property test for invalid credentials
    - **Property 5: Invalid credentials are rejected** — For any non-existent username or wrong password, verify login returns 401
    - **Validates: Requirements 4.2**

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Integrate authentication into API routes (`api.py`)
  - [x] 5.1 Add JWT dependency to existing endpoints in `api.py`
    - Add `user: dict = Depends(get_current_user)` and `db = Depends(get_db)` parameters to `POST /debates`, `GET /debates/{session_id}`, `GET /debates/{session_id}/stream`
    - Keep `GET /settings/defaults` without authentication
    - _Requirements: 5.1, 5.4, 5.5_

  - [x] 5.2 Implement debate persistence in `api.py`
    - In `create_debate`: call `insert_debate(db, session_id, user["id"], ...)` after creating DebateState
    - Modify `_run_debate_task` to accept `db_path` and call `update_debate()` at each phase transition (round_complete → update a_responses/b_responses/phase; synthesis complete → update c1; scoring complete → update scores/phase; failure → update phase to 'failed')
    - In `get_debate_status`: first check in-memory `debates` dict, then fall back to database query; verify user_id ownership for DB results
    - In `stream_debate`: verify the session exists in memory (active debates only) and user has access
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 12.1, 12.2_

  - [x] 5.3 Add new `GET /debates` list endpoint in `api.py`
    - Accept `page` (default=1, ge=1) and `page_size` (default=20, ge=1, le=100) query parameters
    - Call `list_debates(db, user["id"], page, page_size)` and return `PaginatedDebateList`
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x] 5.4 Add new `DELETE /debates/{session_id}` endpoint in `api.py`
    - Query debate by session_id, return 404 if not found
    - Return 403 if debate belongs to different user
    - Delete and return 200 with confirmation message
    - Also remove from in-memory `debates` dict if present
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [ ]* 5.5 Write property test for protected endpoint rejection
    - **Property 6: Protected endpoints reject unauthenticated requests** — For any protected endpoint, verify requests without valid JWT return 401
    - **Validates: Requirements 5.1**

  - [ ]* 5.6 Write property test for user data isolation
    - **Property 7: User data isolation** — For two distinct users, verify user A's debates don't appear in user B's list, and user B cannot access/delete user A's debates
    - **Validates: Requirements 5.4, 8.3**

  - [ ]* 5.7 Write property test for debate deletion
    - **Property 11: Debate deletion removes record** — For any debate owned by authenticated user, verify DELETE returns 200 and subsequent GET returns 404
    - **Validates: Requirements 8.1, 8.4**

- [x] 6. Wire up application startup (`main.py`)
  - [x] 6.1 Update `main.py` lifespan and router registration
    - Import and call `await init_db()` in the lifespan context manager
    - Import and include `auth_router` from `auth.py` via `app.include_router(auth_router)`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [x] 7. Checkpoint - Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Update existing tests for auth compatibility
  - [x] 8.1 Update `tests/test_api.py` to work with JWT authentication
    - Add helper functions to register a test user and obtain a JWT token
    - Update all existing test cases to include `Authorization: Bearer <token>` header
    - Add test for `GET /settings/defaults` without authentication (should still work)
    - Mock or set up test database for each test
    - _Requirements: 5.1, 5.5, 12.2, 12.4_

  - [ ]* 8.2 Write property test for registration-login round trip
    - **Property 12: Registration round trip** — For any valid username and password, verify register then login succeeds and returned JWT grants access to protected endpoints
    - **Validates: Requirements 3.1, 4.1**

  - [ ]* 8.3 Write property test for phase transition persistence
    - **Property 9: Phase transitions persist to database** — Simulate debate progression through pipeline phases, verify each phase transition updates the database row with correct a_responses, b_responses, c1, scores, and phase values
    - **Validates: Requirements 6.2, 6.3, 6.4**

- [x] 9. Implement frontend authentication UI (`static/index.html`)
  - [x] 9.1 Add login/register modal to `static/index.html`
    - Add full-viewport modal HTML with username/password fields and login/register buttons
    - Style consistent with existing dark theme (background #0F172A, card #131825, border #1E2A3A, accent #10B981)
    - All UI text in Traditional Chinese, no emoji
    - On page load: check localStorage for `token`, show modal if absent
    - Login: call `POST /auth/login`, store JWT in localStorage under key `token`, dismiss modal
    - Register: call `POST /auth/register`, show success message prompting user to log in
    - Display error messages within modal on API errors
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

  - [x] 9.2 Add JWT management and auto-logout to `static/index.html`
    - Create a wrapper `apiFetch(url, options)` function that adds `Authorization: Bearer <token>` header to all requests
    - Replace all existing `fetch()` calls to protected endpoints with `apiFetch()`
    - On any 401 response: remove `token` from localStorage, show login modal
    - Keep `GET /settings/defaults` using plain `fetch()` (no auth needed)
    - _Requirements: 10.1, 10.2_

  - [x] 9.3 Add logout button to header in `static/index.html`
    - Add a logout button in the header area next to the existing gear button
    - On click: remove `token` from localStorage, show login modal, reset UI state
    - Style consistent with existing `.gear-btn` style
    - _Requirements: 10.3, 10.4_

- [x] 10. Implement frontend history panel (`static/index.html`)
  - [x] 10.1 Add history button and panel UI to `static/index.html`
    - Add "HISTORY" button in header area next to gear and logout buttons
    - Create history modal/side panel with debate list display area and pagination controls
    - Style consistent with existing dark theme and modal patterns
    - All UI text in Traditional Chinese, no emoji
    - _Requirements: 11.1, 11.2, 11.7, 11.8_

  - [x] 10.2 Implement history panel data loading and interactions
    - Fetch debate list from `GET /debates` with pagination parameters
    - Display each item with: user_input summary (first 50 chars), created_at timestamp, phase status (completed/in-progress/failed)
    - On item click: fetch full debate from `GET /debates/{session_id}`, render complete result in main view (proposals, scoring, pipeline)
    - Add delete button per item: call `DELETE /debates/{session_id}`, remove from list on success
    - Implement pagination: load more control or scroll-based loading
    - _Requirements: 11.2, 11.3, 11.4, 11.5, 11.6_

- [x] 11. Final checkpoint - Ensure all tests pass and existing flow is intact
  - Ensure all tests pass, ask the user if questions arise.
  - Verify SSE streaming, pipeline visualization, proposal cards, radar chart, and score table work identically to current implementation.
  - _Requirements: 12.1, 12.2, 12.3, 12.4_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Active debates use dual-track strategy: in-memory dict for SSE + SQLite for persistence
- All frontend UI text must be Traditional Chinese without emoji
