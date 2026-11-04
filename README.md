# PSIRT CRA 輔助填寫平台

本機逐步式 Web UI 原型，依案件流程協助 PSIRT 整理 D1–D7 資料，顯示 Awareness Time 後的 24／72 小時倒數，並產生表單副本與 SRP 人工填寫參考 PDF。

## 啟動

需要 macOS、Python 3.11 以上，以及能使用登入 Keychain 的桌面工作階段。

安裝與啟動命令：

    python3.13 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    sh run.sh

Git clone 後請在 repository 根目錄執行以上命令。若 Python 3.13 的執行檔名稱不同，請改用已安裝的 Python 3.11 以上版本。

服務只監聽 127.0.0.1:8765。開啟終端機顯示的本機網址使用。第一次啟動會在 macOS Keychain 建立 PSIRT-CRA-Local-Reporting-UI 加密金鑰；若 Keychain 鎖定，請先解鎖再啟動。

## 已實作

- D2、D1、D3、D4、SRP、D5、D6、D7 逐步填寫與流程狀態。
- 對應原始 D1–D6 範本欄位讀取；相同欄位名稱可沿用先前確認的輸入。
- Awareness Time 與 IANA 時區輸入；右側流程 D4 節點顯示 24 小時 Early Warning 與 72 小時 Notification 的即時倒數。兩個期限都從同一 Awareness Time 起算；時間未填時顯示待填，過期後顯示逾期。
- D7 Evidence ID 索引欄位。
- 任一步驟匯出 D1–D7 XLSX 範本副本與一份 SRP Report PDF 的 ZIP，也可逐一下載。
- SRP Report PDF 依選擇的 AEV／SI 類型與 EW／72h／Final 階段，列出 ENISA Glossary 欄位、階段要求、目前資料、來源及 Evidence ID；Intermediate Report 依 CSIRT 個別要求，不套用通用欄位清單。
- 表單欄位變更後自動保存；重新開啟案件可續填。
- 案件資料僅存本機；SQLite 快照與案件內容都使用 AES-GCM 加密。加密金鑰存放在 macOS Keychain。匯出的檔案由瀏覽器下載，不會回寫原始範本。

## 使用界線與待補

- SRP 沒有 API 整合；平台不連線、不操作瀏覽器、不輸入、不提交。
- SRP 欄位清單以 [ENISA CRA SRP Glossary](https://www.enisa.europa.eu/topics/product-security/single-reporting-platform-srp/cra-srp-glossary2) v1.6（2026-10-21 更新；本機於 2026-11-04 核對）及平台 v1.2.1（2026-10-20）整理。這是版本化的本機參考快照，不代表 ENISA 核准本工具或欄位對照；每次填報仍由 SRP AR 核對當前 SRP 畫面及條件式欄位。
- 系統不替人員判定 AEV／重大事件、Awareness Time、CDaC、法規適用性或客戶通知範圍。原有程序書仍須由公司權責人員核准。
- 24 小時與 72 小時倒數都以人員輸入的 Awareness Time 起算，頁面開啟期間每秒更新；關閉平台時不會推播。這是本機提醒，需由權責人員核實知悉時間、適用通報類型及法定期限。ENISA SRP 自身倒數邏輯可能不同，請以當前 SRP 與適用法規為準。
- 自動帶入目前只對相同／已定義為相同的欄位名稱生效；產品版本、影響範圍、措施等時變資料仍應逐次確認。
- 本原型目前沒有多使用者登入、案件權限管理、加密備份／復原介面、金鑰輪替或正式安裝更新流程。正式使用前需完成資安與作業程序覆核。

## 本機資料與原始範本

- 預設加密資料庫：此資料夾下 .data/cases.sqlite3.enc。
- 金鑰：macOS Keychain，不與資料庫放在同一目錄。
- D1–D7 原始範本不包含在程式碼 repository。預設從平台資料夾的上一層讀取；Git clone 後，請將公司核准的範本放在受控位置並設定 `PSIRT_TEMPLATE_DIR`：

      export PSIRT_TEMPLATE_DIR="/path/to/approved/D1-D7-templates"

  匯出時只產生副本，不修改來源。
- ZIP 與 PDF 包含敏感案件資訊，請依公司政策保存與分享。

