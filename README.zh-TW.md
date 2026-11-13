<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/Language-English-blue?style=for-the-badge" alt="English"></a>
  <a href="README.zh-TW.md"><img src="https://img.shields.io/badge/Language-Traditional_Chinese-purple?style=for-the-badge" alt="Traditional Chinese"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/Language-Simplified_Chinese-red?style=for-the-badge" alt="Simplified Chinese"></a>
  <a href="README.es.md"><img src="https://img.shields.io/badge/Language-Spanish-yellow?style=for-the-badge" alt="Spanish"></a>
  <a href="README.ur-pk.md"><img src="https://img.shields.io/badge/Language-Urdu-green?style=for-the-badge" alt="Urdu"></a>
</p>

# 便攜版 Hermes Agent (Portable Hermes Agent)

**專為 Windows 設計的免安裝便攜 AI Agent 桌面版** — 內建 100 種工具、圖形化介面 (GUI)、LM Studio 本地模型、TTS 語音合成、音樂創作、ComfyUI 繪圖、自動化工作流、動態工具製作等。無需安裝、無需 Docker、無需系統管理員權限。

基於 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) (MIT License) 開發，並針對非技術使用者進行了深度優化與便攜化定制。

---

## 主要特色

### 桌面圖形化介面 (GUI)
- 深色現代風格 Tkinter 介面，內建即時交談、側邊欄及對話紀錄管理
- 多語言支援 — 支援英文、繁體中文、簡體中文與西班牙文，可在執行時動態切換
- 支援圖片附件與縮圖預覽（完整支援多模態 Vision 模型）
- 內建模擬引導模式 — 即使尚未連接 AI 模型也能立即使用
- API 金鑰設定精靈，支援個別服務獨立設定
- 細部權限管理面板，精確控制檔案、網路與系統存取權限

### 跨 20+ 工具組的 100 種強大工具

| 工具組 | 工具數 | 功能說明 |
|---------|-------|-------------|
| **LM Studio** | 10 | 載入/卸載模型、搜尋 HuggingFace、Token 計算、向量嵌入、直接交談 |
| **音樂創作 (Music)** | 7 | 生成音樂與音效、模型管理、GPU 加速、成品庫管理 |
| **語音合成 (TTS)** | 7 | 文字轉語音、10 款語音模型、聲音複製、非同步任務管理 |
| **ComfyUI** | 7 | AI 繪圖生成、實例管理、模型與節點瀏覽 |
| **自動化工作流 (Workflows)** | 6 | 建立、執行、排程與管理多步驟自動化流程 |
| **動態工具製作 (Tool Maker)** | 3 | 在執行階段動態封裝 REST API 或撰寫 Python 自訂常駐工具 |
| **Serper** | 1 | 透過 Serper.dev API 獲取 Google 等級優質網路搜尋 |
| **使用手冊 (Guide)** | 1 | 內建可全文檢索使用指南 |
| **GPU 監控** | 1 | NVIDIA GPU 即時狀態監控（顯存、溫度、使用率） |
| **模型切換** | 1 | 在雲端模型與本地 AI 模型之間快速切換 |
| **Hermes 更新** | 2 | 更新上游 Hermes，同時保留所有便攜工具、擴展與執行階段資料 |

外加所有 hermes-agent 內建工具：網路搜尋、檔案操作、瀏覽器自動化、程式碼執行、任務委派、記憶庫、技能、訊息傳遞、Home Assistant 等。

### 擴充套件模組

來自 [aivrar](https://github.com/aivrar) 的三款便攜 AI 生成服務：

| 擴充套件 | 連接埠 | 支援模型 | GPU 顯存需求 |
|-----------|------|--------|------------|
| **[TTS Server](https://github.com/aivrar/portable-tts-server)** | 8200 | Kokoro, XTTS, Dia, Bark, Fish 等 10+ 款 | 4 GB+ |
| **[Music Server](https://github.com/aivrar/portable-music-server)** | 9150 | MusicGen, Stable Audio, ACE-Step, Riffusion | 4 GB+ |
| **[ComfyUI](https://github.com/aivrar/comfyui-portable-installer)** | 5000 | SD 1.5, SDXL, Flux, 100+ 模型 | 6 GB+ |

所有擴充套件皆在初次使用時自動安裝，無任何外部系統相依。

### 工作流程引擎 (Workflow Engine)
將多個工具調用串接為自動化管線，具備資料流傳遞、條件判斷、循環、平行執行、錯誤處理與 cron 定時排程功能。

### 動態工具製作器 (Dynamic Tool Maker)
在執行階段動態建立新工具 — 封裝任何 REST API 或撰寫自訂 Python 處理常式。工具會自動跨對話持久化儲存並自動重載。

### 引導模式 (Guided Mode)
沒有 API 金鑰？沒關係。即使在離線狀態下，也能透過內建的使用手冊正常使用。新用戶可獲得逐步引導以連線至第一個 AI 模型。

---

## 快速開始

從 [Portable Hermes Agent 發行頁](https://github.com/aivrar/portable-hermes-agent/releases/latest)下載 `portable-hermes-agent-v*.zip`，解壓縮到一般資料夾（例如 `C:\Users\YourName\Portable-Hermes-Agent`），避免放在 `C:\Program Files` 等受保護路徑。路徑可以包含空格，但不能包含 `!`、`%` 或 `^`，否則啟動器會拒絕執行。

按兩下 **`START.bat`** 啟動圖形介面；首次啟動會在便攜資料夾中下載內嵌 Python 3.14、**來自 `NousResearch/hermes-agent` 的最新 Hermes Agent 核心**、其精確鎖定的相依套件及 LM Studio SDK，並在另一個程序中確認新核心能與便攜工具及圖形介面一起運作。無人值守安裝可執行 `install.bat --yes`。`hermes_gui.bat` 也會啟動圖形介面，`hermes.bat` 則是命令列入口。無需系統 Python、Docker 或系統管理員權限。

## 兩種獨立的更新方式

Portable Hermes 由**兩個分開更新的部分**組成：

| 部分 | 來源 | 內容 |
|---|---|---|
| **便攜外殼** | [`aivrar/portable-hermes-agent` 發行頁](https://github.com/aivrar/portable-hermes-agent/releases/latest) | Windows 啟動器、圖形介面、便攜工具與技能、安裝與更新程式 |
| **Hermes 核心** | `NousResearch/hermes-agent`（最新 `main`） | Agent 本身 |

關閉 Hermes，執行 **`UPDATE.bat`**。它會先更新便攜外殼（逐一檢查檔案雜湊、只替換便攜檔案，任何步驟失敗都會完整還原），接著顯示核心落後上游多少個提交，並詢問是否更新核心。無人值守：`UPDATE.bat --yes`（只更新便攜外殼）或 `UPDATE.bat --yes --core`（兩者都更新）。也可以在聊天中請 Hermes 檢查或安裝核心更新。

從 v1.4.18 或更早版本升級時，第一次執行 `UPDATE.bat` 會安裝新的啟動器並提示再執行一次 `UPDATE.bat`，第二次執行會完成更新。

**當最新核心需要較新的 Python 時**（v1.4.18 及更早版本安裝的是 Python 3.13，目前的核心需要 3.14），核心步驟會說明將進行的動作，並詢問 `Upgrade the portable Python to 3.14.9 now? [y/N]`。回答 `y` 後，`python_embedded` 會被重新命名為 `python_embedded.old-<版本>`（保留，不刪除），接著下載新的 Python（約 18 MB）與相依套件（通常 150-300 MB）並安裝核心；失敗時會完整復原。回答 `N` 則不做任何變更。`UPDATE.bat --yes --core` 不詢問直接升級。確認 Hermes 正常後可自行刪除舊資料夾。

新核心會先在暫存資料夾中安裝相依套件並在另一個程序中測試，通過後才替換檔案；失敗時檔案會還原，變更過的套件會恢復並經過檢查（若無法全部恢復，更新會明確告知，再執行一次 `UPDATE.bat` 即可完成）。`.env`、`cli-config.yaml`、`HERMES_HOME`（自訂工具、LM Studio 設定、語言偏好）、`extensions\` 與 `workflows\` 永遠不會被更動；`python_embedded\` 只會在安裝核心所需的套件及上述 Python 升級時變更。核心更新後請重新啟動 Hermes。Git 複本（開發者）請使用 `git pull` 更新。

更多操作與最新細節請參閱[英文版便攜 README](README.md)及[發行頁 PDF 手冊](https://github.com/aivrar/portable-hermes-agent/releases/latest)。

---

## 授權條款

本專案基於 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) 開發，採用 [MIT License](LICENSE) 開源協議。
