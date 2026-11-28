# UniXNU — Redmi Turbo 4 Pro（onyx）

[English](README.md) | 简体中文

**实验性重建项目。目前尚未实现任何成功的 UEFI 启动** —— bootloader 接受了镜像，
但还没有观察到固件真正运行。全程未刷写任何分区，所有设备测试都只使用
`fastboot boot`。

## 当前范围

- 目标机型：Redmi Turbo 4 Pro，代号 `onyx`，SM8735，系统 `4.0.4.0.XOLCNXM`
  （fingerprint `Redmi/onyx/onyx:17/CP2A.260605.016/OS4.0.4.0.XOLCNXM:user/release-keys`）。
- 暂定 OS profile：上游 `ipados-17.7.11-21H461`。
- 刻意保持 `board.example = true`，避免把未完成的输入当作生产配置使用。
- 所选用的通用组件**不构成**存储、显示、触控、GPU、网络或电源已可用的证据。
- 最小 DTS 故意保留零尺寸 DRAM；不从其他 SM8735 机型推断内存区间。
- 固件在 [porting.toml](porting.toml) 中状态为 `planned`，所有领域在真机上都未经验证。

## 固件当前进度

Mu-Silicium 的 DEBUG CLANGPDB 构建可以通过，产出的 3 MiB 固件卷通过离线的字节级
验收检查。bootloader 接受该镜像，但至今没有观察到任何固件输出。改动这里任何内容
之前，请先阅读[接手记录](docs/TAKEOVER-UEFI.md)。

### onyx 的 bootloader 会把 `text_offset` 加到跳转地址上

这是目前发现的最关键的板级事实，它推翻了此前所有"被 fastboot 接受、随后黑屏"的观察：

| 字段 | stock `boot_a` | 上游打包器输出 |
| --- | --- | --- |
| `text_offset`（偏移 8） | `0x0` | `0xa7100000`（固件基址） |

ABL 按 `跳转地址 = 加载地址 + text_offset` 计算入口。把固件基址写进该字段，CPU 会被
送到 RAM 之外，于是镜像会报 `Booting OKAY`、**从不执行**，设备随即退回 fastboot。
用只做无条件自跳的探针 shim 验证：仅当该字段被置零后，设备才会真的卡死，机制由此确认。

任何打包流程都必须在打包器自检完成后把 `text_offset` 清零，并把原值记录进
`boot.json`。[scripts/make-menu-image.py](scripts/make-menu-image.py) 已实现这一处理：

```sh
python3 scripts/make-menu-image.py --fd <SILICIUM_UEFI.fd> --dtb <device.dtb> \
  --ramdisk <payload.img> --output out/onyx-menu-boot.img
```

签名不是障碍：把 stock 镜像改坏一个字节后，它依然能正常启动。

## 验证固件卷

验收脚本直接解析 FD 字节：外层 compact FV、GUID 定义的 LZMA 内层 FV，再从 UniXNU
与 Mu_Basecore 的源码中解析 FFS 模块 GUID 进行核对。它同时要求 SEC 交接守卫的诊断
字符串出现在 compact 卷中，因为 `Sec.inf` 位于该卷，而不是解压后的内层卷。

```sh
python3 scripts/accept-firmware.py \
  --fd ../Mu-Silicium/Build/onyxPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd \
  --unixnu ../UniXNU --uefi ../Mu-Silicium --json docs/firmware-acceptance.json
```

必需模块：UniXNU、UniXNUDxe、DarwinBoot、UniXNURamDiskDxe、DiskIoDxe、PartitionDxe、
FAT、英文 Unicode collation、AdvancedLogDxe。该检查只覆盖结构，**不证明**驱动分发、
内存安全或能否启动。

## 检查项

```sh
python3 -m unittest tests.test_accept_firmware tests.test_port_policy tests.test_payload_config
python3 scripts/check-payload-config.py ../menu-payload/EFI/UniXNU/unixnu.toml --unixnu ../UniXNU --require-tools
python3 scripts/check-inputs.py --unixnu ../UniXNU       # 预期失败（fail-closed）
python3 ../UniXNU/scripts/porting-record.py check --device .
```

在示例门禁、DRAM 证据与 `inputs.toml` 来源证明补齐之前，`check-inputs.py` 失败是
**正确**的；不要为了得到一个绿灯结果而放宽它。

`check-payload-config.py` 的存在原因：一份看起来正确的载荷配置可能被固件静默忽略。
`[ui] tools = true` 不会被 `Config.c` 读取（`tools` 是入口 action），而未知键不产生
任何报错——菜单于是根本没有入口可以打开 QR 日志导出。

## 固件补丁

Mu-Silicium 侧的改动以补丁序列形式维护在 [patches/uefi](patches/uefi)：

| 补丁 | 内容 |
| --- | --- |
| `0001`、`0002` | 历史遗留的运行时 FDT 与 Advanced Logger 工作 |
| `0003` | 历史遗留的 BDS 平台选项 |
| `0007` | BootShim：header 描述 shim+FD、保留运行时 `x0`、用 `dc cvac`/`dsb`/`ic iallu`/`isb` 发布重定位后的指令、重叠拷贝改为反向复制 |
| `0008` | SEC：fail-closed 的 FDT/initrd 交接守卫，先判定归属再解引用 |
| `0009` | DSC/FDF：UniXNU 组件栈、Advanced Logger、`FdtLib`、PE 对齐 `0x1000`、`/Brepro` |
| `0010` | BootShim 与交接守卫的主机测试 |
| `0011` | bring-up 报告驱动：把 DXE 检查点画进帧缓冲后停住 |

`0007`–`0010` 可在全新的 `Firef1yfly/Mu-Silicium` 检出上按顺序干净应用。

## 推进顺序

1. 设备只使用 `fastboot boot`，**绝不 `fastboot flash`**。
2. 启动 menu-only 镜像，先确认固件到底有没有跑起来（USB 必须出现断开；若一直停在
   `18d1:d00d`，说明 ABL 根本没有跳转）。
3. 进入可交互的 UniXNU 菜单，并导出一次 Advanced Logger 的二维码日志。
4. 之后才去质证固件设备树、载荷卷大小与内核路径。

第一个里程碑的完成标准：同一镜像哈希连续三次冷启动进入可交互菜单，且每次都保存了
日志。

常用参考：[移植指南](https://unixnu.com/porting/)、[UEFI 固件](https://unixnu.com/porting/uefi-firmware)、
[设备仓库规范](https://unixnu.com/porting/device-repository)、[bring-up](https://unixnu.com/porting/bring-up)。
