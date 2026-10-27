# Cometa USB 驱动（教师使用）

本目录保留厂商驱动包 `EmgMUsbDrivers_3_1_0_0_2017_06_06` 的 `Win10/x64` 原始文件，适用于本课堂使用的 Cometa 基站。INF 中标明版本 `3.1.0.00`，硬件 ID 为 `USB\VID_04B4&PID_1004` / `USB\VID_04B4&PID_1002`。目录名沿用厂商命名；不据此承诺其他型号或所有 Windows 版本兼容。

来源：[Cometa 官方下载入口](https://www.cometasystems.com/downloads/)。原下载文件 `emgmusbdrivers_3_1_0_0_2017_06_06_win10.zip` 的 SHA-256：

```text
c90dfa4a664b1199902afcb08d4c246d929a119ee0e30b1d35a26de2c2922b37
```

发布前，`emgmusb.cat` 的 Windows 签名检查结果为 Valid，签发对象为 Microsoft Windows Hardware Compatibility Publisher。文件校验值见本目录 `SHA256SUMS.txt`。驱动版权属于原厂商。

## 安装

1. 连接基站；确认系统是 Windows x64。
2. 在本目录打开**管理员 PowerShell**，运行：

   ```powershell
   pnputil /add-driver ".\Win10\x64\EmgMUsb.inf" /install
   ```

3. 按 Windows 提示处理；如要求重启，保存工作后重启。设备管理器中确认对应设备没有黄色感叹号。
4. 关闭占用基站的其他采集软件，打开 EMG Lab，选择 Cometa。按实际启用顺序填写传感器编号，连接并观察波形。

保持这 5 个原始驱动文件在同一文件夹，不要单独复制 INF。不要关闭 Windows 驱动签名检查。如果安装失败，保留错误信息交给教师。

## 简单排查

- 找不到基站：检查 USB 连接及设备管理器；Python SDK 安装成功不代表 USB 驱动已安装。
- 基站能连接但某路没有变化：检查该传感器是否启用、已取下充电座、开机且有电，再核对软件中的编号与顺序。
- SDK 加载失败：检查 Windows .NET Framework 及项目依赖；不要混用 Delsys 的 .NET 8 配置。

本机此前已完成驱动安装并读取到传感器数据。本次发行整理没有重新连接设备，不作为四路实时采集验收记录。
