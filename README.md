# PSIRT CRA 輔助填寫平台

本機逐步式 Web UI 原型，依 CRA 程序書 7.1–7.9 引導 PSIRT 填寫案件欄位，顯示 Awareness Time 後的 24／72 小時倒數，並匯出 D1–D7 表單與 SRP Report PDF。

## 執行需求

- Python 3.11 以上。
- 可連線的 PostgreSQL 資料庫。
- `PSIRT_DATABASE_URL`、`PSIRT_SESSION_SECRET`；非 macOS 或無可用登入 Keychain 的服務帳號另需 `PSIRT_ENCRYPTION_KEY`。

## 本機啟動

在 repository 根目錄建立虛擬環境並安裝依賴：

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

建立 PostgreSQL database 與服務帳號後，透過受控環境變數或秘密管理服務提供連線資訊。以下 DSN 僅為格式範例，請勿提交真實密碼或金鑰：

    export PSIRT_DATABASE_URL='postgresql://psirt_app:REPLACE_ME@127.0.0.1:5432/psirt'
    export PSIRT_SESSION_SECRET='REPLACE_WITH_SHARED_RANDOM_SECRET_AT_LEAST_32_CHARACTERS'
    export PSIRT_DB_POOL_SIZE='5'

For repeated local startup, `sh run.sh` also loads an optional repository-root `.env.local` file. Keep that file mode `600`; it is ignored by Git and must not be committed.

在 PostgreSQL 中建立初始 schema，再啟動：

    python manage_db.py upgrade
    sh run.sh

`manage_db.py upgrade` 只建立／升級 schema，不會清除既有 PostgreSQL 資料。應用程式啟動時會拒絕尚未升級或不相容的 schema。正式環境應使用受控資料庫維護帳號升級 schema，再為應用程式設定最小必要權限。

`run.sh` 是本機開發入口，只監聽 `127.0.0.1:8765`。正式部署需由 WSGI 服務管理應用程序，並經公司內部 HTTPS 反向代理提供存取；PostgreSQL port 僅允許應用伺服器連線。

## Docker Compose 本機啟動

需安裝 Docker Engine 與 Docker Compose。首次使用時，在 repository 根目錄建立 `.env.local`，以下指令會產生固定的隨機密碼與金鑰；檔案已存在時不會覆寫：

    (umask 077; set -C; python3 - <<'PY' > .env.local
    import base64
    import secrets
    print(f"PSIRT_POSTGRES_PASSWORD={secrets.token_hex(32)}")
    print(f"PSIRT_SESSION_SECRET={secrets.token_hex(32)}")
    print(f"PSIRT_ENCRYPTION_KEY={base64.b64encode(secrets.token_bytes(32)).decode('ascii')}")
    PY
    )

`PSIRT_POSTGRES_PASSWORD` 使用十六進位字元，讓密碼可直接用於連線 URL。請妥善保存 `.env.local`，不要提交至 Git，也不要在已有案件資料後重新產生加密金鑰。Compose 不會自動讀取 `.env.local`，每次操作都需指定：

    docker compose --env-file .env.local up --build -d
    docker compose --env-file .env.local ps
    docker compose --env-file .env.local logs -f app

開啟 <http://127.0.0.1:8765>。應用容器使用 Gunicorn，等待 PostgreSQL 健康檢查通過後執行 `manage_db.py upgrade`，再啟動 Web 服務；`/health` 亦用於應用容器健康檢查。D1–D7 範本會從 `form/` 複製進映像，修改程式或範本後需重新執行上述建置指令。

PostgreSQL 不對主機發布連接埠，資料保存在 `postgres_data` named volume。停止服務時執行：

    docker compose --env-file .env.local down

`down` 會保留資料；`down -v` 會刪除資料庫 volume 及其中所有案件。此 Compose 設定僅供本機開發，自動升級 schema 使用與應用相同的資料庫帳號；正式部署仍須依前述要求分離維護權限、設定 HTTPS、登入與授權。

## PostgreSQL 整合測試

測試只連接名稱以 `_test` 結尾的專用 PostgreSQL database，並在其中建立唯一暫存 schema；結束後只刪除該暫存 schema。測試不會清空 database 或碰觸正式 schema。

    export PSIRT_TEST_DATABASE_URL='postgresql://tester:REPLACE_ME@127.0.0.1:5432/psirt_test'
    .venv/bin/python -m unittest discover -s tests -v

測試涵蓋 schema 升級重入、健康檢查、AES-GCM payload、過期版本衝突、併發案件編號及刪除／清單操作。未設定測試 DSN 時，整合測試會標示為 skipped。

## 加密與並行控制

- 案件 JSON payload 使用 AES-GCM 加密後存於 PostgreSQL `BYTEA`；案件 ID、建立／更新時間及版本號以欄位保存。PostgreSQL 的資料碟、WAL 與備份仍須使用公司核准的加密及存取控管。
- macOS 會優先使用既有登入 Keychain 案件金鑰；Keychain 找不到金鑰時可由秘密管理服務提供 `PSIRT_ENCRYPTION_KEY`，其他作業系統亦須提供此環境變數。金鑰須為 Base64 編碼的 32 bytes，所有應用程序必須使用同一把；案件資料建立後不可任意更換。
- `PSIRT_SESSION_SECRET` 必須是至少 32 字元的固定隨機值，所有應用程序共用；不可每次啟動重新產生。
- 正式 HTTPS 部署需設定 `PSIRT_COOKIE_SECURE=1`，使 session cookie 僅透過 HTTPS 傳送。
- 每筆案件有資料版本號。瀏覽器送出的版本已過期時，服務回覆 HTTP 409，避免同一案件多人編輯時靜默覆寫；使用者須重新載入最新內容後再套用修改。
- 每年案件編號使用 PostgreSQL 原子序號分配，併發建立不會產生相同編號；失敗建立可能留下號碼空缺，不重用已分配編號。
- `/health` 會檢查 PostgreSQL 連線；連線不可用時回覆 503。

## 目前限制與內網上線門檻

- 本原型尚未實作多使用者登入、角色或案件存取權限。**目前不可直接開放公司網段使用**；在設定內網 HTTPS、來源網段防火牆及應用程式登入／授權前，服務仍只應供本機開發使用。
- PostgreSQL 只提供資料庫連線與交易能力，不會自行提供應用程式身份驗證或案件授權。
- SRP 沒有 API 整合；平台不連線、不操作瀏覽器、不輸入、不提交。
- 系統不替人員判定 AEV／重大事件、Awareness Time、CDaC、法規適用性或客戶通知範圍。
- 24／72 小時倒數在頁面開啟期間更新；關閉平台時不會推播。期限及適用類型仍須由權責人員核實。
- 目前沒有加密備份／復原介面、金鑰輪替或正式安裝更新流程；正式使用前須完成資安與作業程序覆核。

## 案件範本與匯出

- D1–D7 原始範本預設放在 repository 根目錄的 `form/` 資料夾，平台從該處讀取。若要改用其他受控位置，可設定 `PSIRT_TEMPLATE_DIR` 覆寫預設路徑：

      export PSIRT_TEMPLATE_DIR="/path/to/approved/D1-D7-templates"

- 匯出只產生範本副本，不修改來源。ZIP 與 PDF 包含敏感案件資訊，依公司政策保存與分享。
- 現有加密 SQLite 資料不會自動匯入 PostgreSQL。此次資料重置後，PG 初始案件清單為空；舊 SQLite 快照已依授權清除。
