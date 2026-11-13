# 便携版 Hermes Agent (Portable Hermes Agent)

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/Language-English-blue?style=for-the-badge" alt="English"></a>
  <a href="README.zh-TW.md"><img src="https://img.shields.io/badge/Language-Traditional_Chinese-purple?style=for-the-badge" alt="Traditional Chinese"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/Language-Simplified_Chinese-red?style=for-the-badge" alt="Simplified Chinese"></a>
  <a href="README.es.md"><img src="https://img.shields.io/badge/Language-Spanish-yellow?style=for-the-badge" alt="Spanish"></a>
  <a href="README.ur-pk.md"><img src="https://img.shields.io/badge/Language-Urdu-green?style=for-the-badge" alt="Urdu"></a>
</p>

**面向 Windows 的便携 AI 助手桌面版**：图形界面、100 种工具、通过 LM Studio 使用本地模型，以及语音、音乐、ComfyUI、工作流和自定义工具。无需在系统中安装 Python 或 Node.js，也无需 Docker 或管理员权限。

本项目基于 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)（MIT 许可证），但这是 **aivrar 的便携发行版**。请从本仓库的发行页下载；上游 Hermes 的安装说明不适用于此便携包。

---

## 功能

- 深色 Tkinter 图形界面，包含聊天、侧边栏、会话管理、图片附件、引导模式、API 密钥向导及权限面板。
- 界面支持英语、繁体中文、简体中文和西班牙语，可在运行时切换。
- 20 多个工具组共约 100 种工具，包括 LM Studio、文字转语音、音乐生成、ComfyUI、工作流、工具制作器、搜索、GPU 状态和内置手册。
- 首次使用时可在便携环境中安装 [TTS Server](https://github.com/aivrar/portable-tts-server)、[Music Server](https://github.com/aivrar/portable-music-server) 和 [ComfyUI](https://github.com/aivrar/comfyui-portable-installer) 扩展。
- 同时提供 Hermes Agent 的网络搜索、文件操作、浏览器自动化、记忆、技能和消息平台等功能。

LM Studio 面板将服务器地址及可选 API 密钥保存在当前 `HERMES_HOME` 中的 `.lmstudio_config`，而不是应用源代码内。两种更新方式都会保留这些用户数据，发行 ZIP 不包含它们。请妥善保管密钥；清空密钥输入框并点击“保存”即可移除已保存的密钥。

---

## 快速开始

1. 从 [Portable Hermes Agent 发行页](https://github.com/aivrar/portable-hermes-agent/releases/latest)下载最新的 `portable-hermes-agent-v*.zip`，解压到普通文件夹，例如 `C:\Users\YourName\Portable-Hermes-Agent`。不要放在 `C:\Program Files` 等受保护目录。
2. 双击 **`START.bat`**。首次启动会在便携文件夹内下载内嵌 Python 3.14、**来自 `NousResearch/hermes-agent` 的最新 Hermes Agent 核心**、其精确锁定的依赖和 LM Studio SDK，并在单独的进程中确认新核心可以与便携工具和图形界面一起工作；无需管理员权限。
3. 使用图形界面中的 API 密钥设置向导连接云端模型，或启动 [LM Studio](https://lmstudio.ai) 的本地服务器并在 LM Studio 面板选择模型。

| 文件 | 用途 |
|---|---|
| `START.bat` | 最简单的图形界面启动方式 |
| `UPDATE.bat` | 更新便携外壳，确认后再更新核心 |
| `hermes_gui.bat` | 启动图形界面 |
| `hermes.bat` | 启动命令行 |
| `install.bat` | 手动执行首次准备 |

无人值守安装可运行 `install.bat --yes`。

## 两种独立的更新方式

Portable Hermes 由**两个分别更新的部分**组成：

| 部分 | 来源 | 内容 |
|---|---|---|
| **便携外壳** | [`aivrar/portable-hermes-agent` 发行页](https://github.com/aivrar/portable-hermes-agent/releases/latest) | Windows 启动器、图形界面、便携工具与技能、安装与更新程序 |
| **Hermes 核心** | `NousResearch/hermes-agent`（最新 `main`） | Agent 本身 |

关闭 Hermes 后双击 **`UPDATE.bat`**。它先更新便携外壳（逐个校验文件哈希、只替换便携文件，任何一步失败都会完整还原），然后显示核心落后上游多少个提交，并询问是否更新核心。无人值守：`UPDATE.bat --yes`（只更新便携外壳）或 `UPDATE.bat --yes --core`（两者都更新）。也可以在聊天中让 Hermes 检查或安装核心更新。

新核心会先在暂存目录中安装依赖并在单独的进程中测试，通过后才替换文件；失败时文件和依赖包都会还原。`.env`、`cli-config.yaml`、`HERMES_HOME`（自定义工具、LM Studio 设置、语言偏好）、`python_embedded\`、`extensions\` 和 `workflows\` 永远不会被改动。核心更新后请重启 Hermes。Git 克隆（开发者）请使用 `git pull` 更新。

---

## 系统要求与文档

- Windows 10 或 11。
- 云端模型需要网络连接；本地模型建议使用具备至少 8 GB 显存的 NVIDIA GPU。
- 不需要系统 Python、系统 Node.js、Docker 或管理员权限。

程序内置可搜索的使用手册（`search_guide`）；每个[发行版本](https://github.com/aivrar/portable-hermes-agent/releases/latest)还附有 PDF 手册。未翻译的最新细节请参阅[英文便携版 README](README.md)。

## 致谢与许可证

原始框架：[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)（MIT 许可证）。便携扩展：[aivrar](https://github.com/aivrar)。许可证详见 [LICENSE](LICENSE)。
