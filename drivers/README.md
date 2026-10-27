# 设备驱动

只使用模拟信号或文件回放时，不需要安装本目录中的驱动。先完成根目录的 `install.cmd`，再运行 `start.cmd` 即可。

| 设备 | 本项目提供 | 真实设备额外准备 |
| --- | --- | --- |
| Cometa 基站 | [Windows x64 USB 驱动与安装说明](cometa/README.md)、`vendor/cometa` SDK 适配层 | USB 驱动、Windows .NET Framework、基站和已启用传感器 |
| Delsys | `vendor/delsys` SDK 适配层、`examples/delsys.example.json` 配置示例 | 厂商 USB 驱动、.NET 8、合法 SDK 许可；按助教说明配置 `local/delsys.json` |
| Revo2 灵巧手 | `emg_lab/hand/driver` 适配层、Python USB 依赖 | 教师配置对应 USB 适配器驱动、供电和硬件编号 |
| 机器人仿真 | MuJoCo、场景、运控策略和 Python 依赖 | 支持 OpenGL 的显卡驱动 |

`install.cmd` 安装 Python 依赖，不会修改 Windows 设备驱动。第三方 SDK 的 DLL 和 Python 包也不能替代设备 USB 驱动。课堂学生不需要配置真实机器人或真实灵巧手。
