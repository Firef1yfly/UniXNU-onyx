# UniXNU — Redmi Turbo 4 Pro（onyx）

[English](README.md) | 简体中文

**实验性重建项目。目前尚未实现任何成功的 UEFI 启动** —— 在真机上观察到固件已经跑完
DXE 派发，随后落入平台的 unable-to-boot 路径（灰屏），但从未到达任何启动项、菜单或
操作系统。全程未刷写任何分区，所有设备测试都只使用 `fastboot boot`。

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
验收检查。在真机上该固件卷派发了整套 DXE 驱动——面板上留下三屏经平台 `SerialPortLib`
输出的 `DEBUG` 文本——随后停在灰屏，也就是平台 BDS 放弃所有启动项时绘制的
`PlatformBootManagerUnableToBoot` 画面。现在交棒由 `PlatformBootManagerAfterConsole()`
经平台的 `DeviceBootManagerLib` 负责，只要应用还在固件卷里，BDS 就不会再走到那条路径。
以上都还没有到达菜单。改动这里任何内容
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
python3 -m unittest discover -s tests -p 'test_*.py'      # 203 项；依赖上游树的用例会跳过
UNIXNU_UEFI=../Mu-Silicium python3 scripts/check-firmware-inputs.py
python3 scripts/check-payload-config.py ../menu-payload/EFI/UniXNU/unixnu.toml --unixnu ../UniXNU --require-tools
python3 scripts/check-inputs.py --unixnu ../UniXNU       # 预期失败（fail-closed）
python3 ../UniXNU/scripts/porting-record.py check --device . --base origin/main
```

`scripts/check-firmware-inputs.py` 是 board.toml 里的 `[firmware] preflight`，官方固件
构建步骤也会执行它。它把补丁序列涉及到的每个文件与该序列记录的 blob 逐一比对——因此
"少打一个补丁的源码树"、"手改过的文件"、"缺失文件"都会被拒——同时拒绝这些情况：
Mu-Silicium `onyx.toml` 的 `uefi_fd` 基址/尺寸、压缩设置或 header 版本漂移；`board.toml`
的压缩设置与固件侧不一致；`onyx.dsc`/`onyx.fdf` 丢失 PE 对齐、`FdtLib` 映射、
`-DONYX_FDT_HANDOFF=1` 开关或八个必需模块中的任何一个。没有 `UNIXNU_UEFI` 时它跳过并
说明原因，因为 `unixnu package --check` 会在没有固件检出的机器上运行它。

移植记录检查由 CI 在每次推送时执行，且以 `origin/main` 为基准比较推送区间：改了受管路径
却没同步更新该领域的 findings 会直接失败。`tests/test_porting_record.py` 跑的就是同一条
命令，所以这类失败会先在本地暴露。

在示例门禁、DRAM 证据与 `inputs.toml` 来源证明补齐之前，`check-inputs.py` 失败是
**正确**的；不要为了得到一个绿灯结果而放宽它。

`check-payload-config.py` 的存在原因：一份看起来正确的载荷配置可能被固件静默忽略。
`[ui] tools = true` 不会被 `Config.c` 读取（`tools` 是入口 action），而未知键不产生
任何报错——菜单于是根本没有入口可以打开 QR 日志导出。

## 固件补丁

Mu-Silicium 侧的改动以补丁序列形式维护在 [patches/uefi](patches/uefi)：

| 补丁 | 内容 |
| --- | --- |
| `0001` | BootShim：保留运行时 FDT，header 描述 shim+卷 |
| `0007` | BootShim：header 描述 shim+FD、保留运行时 `x0`、用 `dc cvac`/`dsb`/`ic iallu`/`isb` 发布重定位后的指令、重叠拷贝改为反向复制 |
| `0008` | SEC：fail-closed 的 FDT/initrd 交接守卫，先判定归属再解引用 |
| `0009` | DSC/FDF：UniXNU 组件栈、Advanced Logger、`FdtLib`、PE 对齐 `0x1000`、`/Brepro` |
| `0010` | BootShim 与交接守卫的主机测试 |
| `0011` | bring-up 报告驱动：用 `DEBUG` 输出 DXE 检查点后停住板子 |
| `0012` | UniXNUDxe：BDS 无启动项时的直接启动兜底（保留其注册与标记；真正生效的是 `0014`） |
| `0013` | 上述启动路径的主机测试 |
| `0014` | `DeviceBootManagerLib`：交棒发生在 `DeviceBootManagerAfterConsole()`，早于 BDS 读取任何启动项，只要应用在卷里，`PlatformBootManagerUnableToBoot()` 就不可达 |

`0002`、`0003` 已撤回，内容并入 `0007`、`0008`、`0009`。其余序列可在全新的
`Firef1yfly/Mu-Silicium` 检出上按顺序干净应用，并精确重建出产出"已验收固件卷"的那棵树
——`scripts/check-firmware-inputs.py` 用 blob 校验这一点，`tests/test_uefi_patch_series.py`
固定每个补丁归属哪个检出（`0012` 作用于 UniXNU 树，`git apply` 必须带 `--directory=package`）。

## 推进顺序

1. 设备只使用 `fastboot boot`，**绝不 `fastboot flash`**。
2. 每次上机都走 [scripts/device-ladder.py](scripts/device-ladder.py)：
   `boot --image … --confirm-sha256 … --cold-restart` 会拒绝哈希不符或 `text_offset`
   不为零的镜像，写出记录，并根据轮询到的设备在位序列给出判定。单次 `Booting OKAY`
   **从不**算通过。
3. 用 `device-ladder.py attach --photo … --note …` 把面板照片绑到那条记录上，让"菜单出现"
   的画面与产出它的镜像哈希绑定，而不是与记忆中的某次运行绑定。
4. 进入可交互的 UniXNU 菜单，并导出一次 Advanced Logger 的二维码日志。
5. 之后才去质证固件设备树、载荷卷大小与内核路径。

第一个里程碑的完成标准：同一镜像哈希连续三次冷启动进入可交互菜单，且每次都保存了
日志。

常用参考：[移植指南](https://unixnu.com/porting/)、[UEFI 固件](https://unixnu.com/porting/uefi-firmware)、
[设备仓库规范](https://unixnu.com/porting/device-repository)、[bring-up](https://unixnu.com/porting/bring-up)。
