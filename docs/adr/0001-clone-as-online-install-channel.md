# 源码 clone/ZIP 成为受支持的联网安装渠道；运行时工件钉死 python.org NuGet 3.13.5

学生此前只能通过学生离线包安装；现在 git clone 或网页 ZIP 解压后联网运行
install.cmd 也是正式渠道——缺本地运行时且无系统 Python 3.13 时，install.cmd
按运行时锁（版本 3.13.5 + SHA256，锁内含官方 nuget.org 与自管 GitHub Release 镜像双来源）自动**取回**
python.org 官方 NuGet 包到 `.runtime\`，与离线包携带的运行时逐字节同源、
布局相同，后续安装流程零分叉。学生离线包仍是课堂弱网/无网环境的首选，
在线渠道是公开可及的正式入口，不是备用路径。

## Considered Options

- **只保留学生离线包渠道**：被否——公网学生获取离线包本身就要网络，且离线包
  分发链路（教师手动发放）不可扩展。
- **python.org embeddable zip 作为取回工件**：被否——它剥离了 `venv` 与
  `ensurepip`，bootstrap.py 建环境必然失败；NuGet 包是全功能解释器，已被
  离线包验证。
- **优先取回、弃用系统解释器**：被否——机器已有 Python 3.13 时不该再花流量；
  取回仅作末位兜底（解释器优先级链）。
