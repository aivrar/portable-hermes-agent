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

從 [Portable Hermes Agent 發行頁](https://github.com/aivrar/portable-hermes-agent/releases/latest)下載 `portable-hermes-agent-v*.zip`，解壓縮到一般資料夾（例如 `C:\Users\YourName\Portable-Hermes-Agent`），避免放在 `C:\Program Files` 等受保護路徑。

按兩下 **`START.bat`** 啟動圖形介面；首次啟動會在便攜資料夾中準備內嵌 Python、相依套件及所需工具。`hermes_gui.bat` 也會啟動圖形介面，`hermes.bat` 則是命令列入口。無需系統 Python、Docker 或系統管理員權限。

## 兩種獨立的更新方式

| 更新項目 | 來源 | 操作 |
|---|---|---|
| **便攜版發行套件** | `aivrar/portable-hermes-agent` | 關閉 Hermes，執行 **`UPDATE.bat`**；更新啟動器、GUI、便攜工具與此專案測試過的 Hermes 版本 |
| **內部的上游 Hermes Agent** | `NousResearch/hermes-agent` | 啟動 Hermes，先要求檢查上游更新；確認後再要求更新，同時保留便攜版自訂項目 |

更新其中一項**不會**自動更新另一項。一般更新可執行 `UPDATE.bat`，或使用 `hermes.bat update --backup --yes`。更新會保留使用者資料、自訂工具、擴充套件與內嵌 Python；上游更新完成後請重新啟動 Hermes。ZIP 安裝即使沒有 Git 歷史，也能使用上游覆蓋更新模式。詳見 [便攜版更新指南](https://github.com/aivrar/portable-hermes-agent/wiki/Keeping-Portable-Hermes-Updated)。

更多操作與最新細節請參閱[英文版便攜 README](README.md)及[發行頁 PDF 手冊](https://github.com/aivrar/portable-hermes-agent/releases/latest)。

---

## 授權條款

本專案基於 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) 開發，採用 [MIT License](LICENSE) 開源協議。
