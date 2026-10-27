# 帮助窗口本地脚本（help_assets）

离线帮助窗口（`emg_lab/help.py`）用 QtWebEngine 加载以下本地脚本渲染
Markdown、Mermaid 图与代码高亮，运行时不访问网络。marked、mermaid 为 MIT
许可，highlight.js 为 BSD-3-Clause 许可。

| 文件 | 版本 | 来源 | SHA-256 |
| --- | --- | --- | --- |
| `emg_lab/help_assets/marked.min.js` | marked 18.1.2 | `https://cdn.jsdelivr.net/npm/marked@18.1.2/lib/marked.umd.min.js`（jsDelivr Terser 自动压缩） | `47273743d43aa0f1ed23d7cf3f6ae4ebf9086d016cfd5fb9f11ee5b9ea2dc529` |
| `emg_lab/help_assets/mermaid.min.js` | mermaid 12.2.0 | `https://cdn.jsdelivr.net/npm/mermaid@12.2.0/dist/mermaid.min.js` | `a8a6a6f805b074a8261a2825c86f99c8054acb3b35f50bb7e24a4f9f2c3c3b9f` |
| `emg_lab/help_assets/highlight.min.js` | highlight.js 11.12.0（common 包，36 语言，含 python/json，不含 powershell） | `https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.12.0/highlight.min.js` | `8ab71eb09c51f501e5e25157d9cff100e46cc29bcbfc744d0b746d451fca7f53` |
| `emg_lab/help_assets/highlight-powershell.min.js` | highlight.js 11.12.0（powershell 语言包） | `https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.12.0/languages/powershell.min.js` | `fc298b3e0db362e531e6d58988b7a78f83da19df6b5d74db75bc961b2bfbfd3d` |
| `emg_lab/help_assets/highlight-github.min.css` | highlight.js 11.12.0 官方 github 浅色主题 | `https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.12.0/styles/github.min.css` | `3a9a5def8b9c311e5ae43abde85c63133185eed4f0d9f67fea4b00a8308cf066` |

`help.css` 为本项目自写样式，与 `emg_lab/theme.py` 的字体和配色一致；
其中对 `.hljs` 容器（底色、内边距、换行）的覆盖优先于主题文件。

许可证原文：[marked-LICENSE](marked-LICENSE)、[mermaid-LICENSE](mermaid-LICENSE)、
[highlightjs-LICENSE](highlightjs-LICENSE)。
升级版本时应更新本表与哈希，并重跑 `scripts/check_help.py`。
