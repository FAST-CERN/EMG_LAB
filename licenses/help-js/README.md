# 帮助窗口本地脚本（help_assets）

离线帮助窗口（`emg_lab/help.py`）用 QtWebEngine 加载以下本地脚本渲染
Markdown 与 Mermaid 图，运行时不访问网络。两个库均为 MIT 许可。

| 文件 | 版本 | 来源 | SHA-256 |
| --- | --- | --- | --- |
| `emg_lab/help_assets/marked.min.js` | marked 18.1.2 | `https://cdn.jsdelivr.net/npm/marked@18.1.2/lib/marked.umd.min.js`（jsDelivr Terser 自动压缩） | `47273743d43aa0f1ed23d7cf3f6ae4ebf9086d016cfd5fb9f11ee5b9ea2dc529` |
| `emg_lab/help_assets/mermaid.min.js` | mermaid 12.2.0 | `https://cdn.jsdelivr.net/npm/mermaid@12.2.0/dist/mermaid.min.js` | `a8a6a6f805b074a8261a2825c86f99c8054acb3b35f50bb7e24a4f9f2c3c3b9f` |

`help.css` 为本项目自写样式，与 `emg_lab/theme.py` 的字体和配色一致。

许可证原文：[marked-LICENSE](marked-LICENSE)、[mermaid-LICENSE](mermaid-LICENSE)。
升级版本时应更新本表与哈希，并重跑 `scripts/check_help.py`。
