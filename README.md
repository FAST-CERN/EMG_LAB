# EMG Lab 肌电控制实验

课堂版 `2026.10.26-classroom.2`。完成 **连接设备 → 采集数据 → 训练模型 → 使用模型**；机器人和灵巧手共用同一操作流程。两组各 6 人，每组两条线各约 3 人。

## 开始使用

**完整离线包同时包含源码、文档、场景、驱动和 Python 运行依赖**。完整解压后按下列步骤操作，无需先安装 Python。

离线发行包完整解压后双击 `start.cmd`，首次启动自动使用随包 Python、uv 和锁定 wheel 建立本目录的 `.venv`，无需联网。安装中断可重试，修复可运行 `install.cmd`。移动文件夹后会重新建立环境；不要复制其他电脑的 `.venv`。

当前 Git 仓库是源码，不包含运行时与 wheelhouse。开发时安装 uv 后运行：

```powershell
uv sync --locked
uv run --locked python main.py
```

Windows 源码安装也可运行 `install.cmd`：缺少 Python 3.13 时保留原有按 SHA256 验证的 NuGet 3.13.5 获取链，再使用 uv 同步锁定依赖。目标是 Windows 10 22H2 / Windows 11 x64，3D 需要 OpenGL；本次 Linux 工作区尚未完成 Windows GUI 验收。

[重构报告](docs/RESTRUCTURE_REPORT.md)记录架构与当前验证范围，[离线发行与验收](docs/WINDOWS_RELEASE.md)说明如何生成真正包含运行依赖的 ZIP。当前尚未下载运行时与全部 Windows wheel，因此本次没有生成可分发 ZIP。

## 课堂功能

| 方向 | 基础 | 扩展 |
| --- | --- | --- |
| 机器人 | 停止、前进、左转、右转 | 加入后退、左移、右移，共七类 |
| 灵巧手 | 停止保持、张开、握合 | 停止保持与四个官方预设姿态，共五类 |

采集默认 5 组，每动作 5 秒、准备 3 秒。可复用简短采集记录，采集中可将错误的一组标记无效；训练与基础评估自动排除，原始数据保留。模型采用因果滤波、滑窗、一维卷积分类与稳定判定，按完整动作组划分训练、验证和测试。

采集场景演示提示动作；实时与离线推理场景由模型预测驱动。自由练习、基础评估、机器人金币任务各有独立用途。基础评估报告显示准确率、混淆、停止误触发、响应和切换统计；从数据与模型页打开或导出历史报告。

数据与模型页统一筛选、导入导出。`.emg` 包含原始信号、标签和元数据；`.emgmodel` 包含 ONNX 和模型说明。界面导出的离线实验包只包含数据/模型，配合教师发放的完整学生包使用。可运行合成 smoke 命令检查软件流程。

机器人采集页另提供[自定义动作采集](docs/CUSTOM_CAPTURE.md)：可配置最多 64 个动作/力道条件，支持轮采和单动作补采，保存原始 `.emg` 与动作索引 CSV；暂不关联机器人训练或控制。

## 文档与代码

- [操作教程](docs/USER_GUIDE.md)、[课程约定](docs/COURSE_GUIDE.md)
- [开发技术文档](docs/TECHNICAL_GUIDE.md)：链路、目录、数据结构、算法与扩展接口
- [设备驱动与安装说明](drivers/README.md)：Cometa 原厂 USB 驱动、SDK 与 Python 依赖的区别
- [金币任务规则](docs/COMPETITION.md)、[速度实验记录](docs/CONTROL_ENVELOPE_V2.md)、[手部姿态来源](docs/HAND_POSES.md)

`emg_lab/frontend/` 是 Qt 前端，`emg_lab/backend/` 是无 Qt 的后台，`emg_lab/contracts/` 是共享契约；`emg_lab/` 根部旧模块保留兼容导入，`assets/` 是场景与运控资源，`vendor/` 为设备适配依赖，`scripts/` 与 `tests/` 为检查入口，`licenses/` 保留第三方许可。个人结果保存到 `data/`，运行日志保存到 `local/`，发行包不含真实采集记录、许可凭据或个人日志。

源码目录包含应用、资源、驱动和文档；离线包另带 `.runtime/` 与 `wheelhouse/`。个人结果与运行日志在首次使用后生成，`.gitignore` 已排除这些目录。第三方来源与使用范围见 [NOTICE](NOTICE.md)。

## 验证范围

运行 `uv run python scripts/check_classroom.py --render` 检查软件与 3D，不连接硬件。自动化回归：`uv run pytest -q`；明确的合成全链路检查：`uv run python scripts/smoke_pipeline.py --output local/smoke`。合成结果仅验证软件流程。Windows 离线包用 `acceptance.cmd --relocation-test` 验证；Qt、Windows 和真实硬件检查的待办状态见重构报告。

机器人金币任务所有模型同榜；固定分类速度固定，教师验收的连续/混合方法可用较高速度上限。底层运控、种子、加速度及计时规则共同冻结。学生改进算法后仍可练习，正式比赛由教师审核并冻结版本。

机器人七类与手部五类目前仅用于仿真；手部显示是姿态运动学，未实现接触力或抓取精度测量。基础三类的定速握合加停止不等于肌电强度连续解码。真实硬件连接由教师安排；模拟、回放与采集演示不启用真机动作输出。
