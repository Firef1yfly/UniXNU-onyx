# Mu → UniXNU 菜单离线复核

## 结论范围

本记录绑定已知进入 Mu-Silicium、随后显示 `No Operating System Found` 的固定
Android v4 镜像。用户还报告过更早的仓库版本显示 Apple-logo UniXNU 菜单，但
当前没有把那个观察绑定到这个精确 SHA-256；两项历史事实不能合并为同一产物验证。
本记录不声称当前源码重建或无设备验证成功。未连接设备、未运行 build、未修改
Mu-Silicium 或 UniXNU 的固件源码，也未启用 OnyxBootOptions。

固定输入：

- 镜像：`/home/firefly/UniXNU/out/onyx/ios-17.7.11-21H461/example/boot/boot.img`
- whole-image SHA-256：`f84337c7aa91436779844b6d86f8829d83461592e27edbbb7241378dba5985c2`
- FD SHA-256：`a7fbef72f78b7e5e4e14680cd6fe85429db866a0e16c5931208db4d53e69d20e`
- 外层包装配置：Android header v4、kernel compression `none`、FD 3 MiB、DTB appended。

机器可读摘要见 [`baseline.json`](../../../out/onyx-bringup/menu/baseline.json)。

## 历史镜像布局

历史镜像 kernel field 是未压缩的 `BootShim + FD + appended DTB`：

| 区段 | 镜像偏移 | 大小 | SHA-256 |
| --- | ---: | ---: | --- |
| BootShim | `0x1000` | 128 | `7d40b171cb39a311d522bada00df2d857046fd1ef109462494d1f5c50a606594` |
| FD | `0x1080` | `0x300000` | `a7fbef72f78b7e5e4e14680cd6fe85429db866a0e16c5931208db4d53e69d20e` |
| appended DTB | `0x301080` | 879313 | `6379d64c8472c7c4c2d9d225803bebe33b8bd2c14cb73c6b329a8a5458dd6f23` |
| FAT ramdisk | Android page-aligned区段 | 201326592 | `be6aeabf340f9e06e3bb31adb40787af1f96cfda774a7892e7901361418cc521` |

FD 内部不是简单把整个文件当 FV 数据：历史 FD 开始处是
`FVMAIN_COMPACT` 的 72-byte FV header（文件偏移 `0x28` 的 `_FVH`），其
`FvLength=0x300000`。直接对历史 FD 运行 `VolInfo` 得到 nested FV 文件 GUID
`9E21FD93-9C72-4C15-8C4B-E77F1DB2D792`，实际 FFS file offset 为 `0xD000`、
长度为 `0x1330D0`；不能用当前 `FVMAIN_COMPACT.Fv.txt` 的 `0x10000` 代替
历史 FD 本体布局。

该文件中的 GUID-defined section 使用 LZMA guided format。取 section data、经
EDK2 `LzmaCompress -d` 解码并跳过 8-byte 长度头，得到大小 `0x7BE000`、
SHA-256 `f8f28a02a0969e4f132d33160c3e7f37694e23c276b224685247dcfd5e6b944b`
的主 FV。对这个主 FV 运行 `VolInfo` 得到 109 个 FFS，并直接确认：

| 文件 | FILE_GUID |
| --- | --- |
| `DiskIoDxe` | `6B38F7B4-AD98-40E9-9093-ACA2B5A253C4` |
| `PartitionDxe` | `1FA1F39E-FEFF-4AAE-BD7B-38A070A3B609` |
| `Fat` | `961578FE-B6B7-44C3-AF35-6BC705CD2B1F` |
| `EnglishDxe` | `CD3BAFB6-50FB-4FE8-8E4E-AB74D2C1A600` |
| `ConPlatformDxe` | `51CCF399-4FDF-4E55-A45B-E123F84D456A` |
| `ConSplitterDxe` | `408EDCEC-CF6D-477C-A5A8-B4844E3DE281` |
| `GraphicsConsoleDxe` | `CCCB0C28-4B24-11D5-9A5A-0090273FC14D` |
| `SimpleFbDxe` | `DCFD1E6D-788D-4FFC-8E1B-CA2F75651A92` |
| `UniXNURamDiskDxe` | `75CA63AD-FBAE-4A06-92A0-F937C671251D` |
| `UniXNUDxe` | `29B950CF-586D-49EA-9D71-F88645CCDAF6` |
| `UniXNU` application | `9B665204-A133-47A2-9396-9E2B370A4E25` |
| `DarwinBoot` | `1B64AF87-8415-4B57-9B16-680D70913B9F` |

外层 `FVMAIN_COMPACT` 的 FV header GUID 为
`8C8CE578-8A3D-4F1C-9935-896185C32DD3`，nested FV 文件 GUID 为
`9E21FD93-9C72-4C15-8C4B-E77F1DB2D792`。这里的模块结论来自历史 FD
本体的解压和解析，不是把当前 `FVMAIN.Fv.txt` 构建清单当成产物证明。

## 最低启动链（历史证据 + 源码静态核对）

1. Android bootloader 载入并执行 BootShim；BootShim 将 Mu FD 与输入 DTB 交给
   SEC/UEFI。此历史镜像使用 128-byte shim、FD 3 MiB 和完整 appended DTB。
2. Mu DXE dispatches BDS 及平台库。`BdsEntry.c:720` 调用
   `PlatformBootManagerBdsEntry()`；`BdsEntry.c:926-928` 调用
   `PlatformBootManagerBeforeConsole()`。
3. onyx 平台 `BootManager.c:39-58` 在 BeforeConsole 中执行 deferred images，
   然后调用 `MsBootOptionsLibRegisterDefaultBootOptions()`，再更新 ConIn/
   ConOut/ErrOut，最后执行设备平台回调。
4. 历史 UniXNUDxe 是 DXE driver。其源码
   `package/UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.c:159-207` 在 FV2 中查找
   `PcdUniXNUApplicationFile`（默认应用 GUID
   `9B665204-A133-47A2-9396-9E2B370A4E25`），序列化 Boot####，通过标准
   `gRT->SetVariable` 写入；`:212-229` 将该编号移到 BootOrder 首位。
5. BDS `BdsEntry.c:1135-1146` 重新读取 BootOrder；`BootBootOptions()`
   `:394-411` 只尝试 `LOAD_OPTION_ACTIVE` 且 category 等于
   `LOAD_OPTION_CATEGORY_BOOT` 的项。UniXNU option 必须满足这两个条件；
   `APP`/`HIDDEN` 项会被跳过而不是启动。
6. `EfiBootManagerBoot()` 通过 FV device path 连接并 `LoadImage()`；同 FV 的
   `UniXNU.efi` 若 PE32/FV 解析或 StartImage 失败，BDS 会记录该项失败并继续。
   若没有任何成功选项，才进入 `PlatformBootManagerUnableToBoot()`，即
   Mu `BootManager.c:203-224` 的 no-OS 图形/文本、10 秒停顿和 shutdown。
7. UniXNU 应用入口调用 `UniXNURun(ImageHandle, Host)`。Firmware marker
   由 `UniXNU.c:31-39` 识别为 `HostFirmware`。
8. `UniXNURun()` 先连接控制器，再读配置；缺少
   `\\EFI\\UniXNU\\unixnu.toml` 时 `Config.c:1567-1597` 使用内置配置，
   不会因此回到 BDS。内置 default index 为 0 (`exit`)，不是自动立即退出：
   `Menu.c:114-120` 的计时结束后才选择默认项。为复现“菜单出现”，必须在倒计时
   内停止/选择，不能把默认 exit 后的 BDS no-OS 误认为菜单未启动。
9. UI 先从 `ConsoleOutHandle` 获取 GOP（`Ui.c:658-672`），失败才
   `LocateProtocol`；若 GOP 不可用则尝试 `gST->ConOut` 文本模式
   (`Ui.c:686-689`)。图形路径使用 GOP `Blt`，不会向 ConOut 打字覆盖面板
   (`Ui.c:1-6`, `:741-763`)。因此菜单复现的观察点是 GOP 画面或明确的 ConOut
   文本 fallback，而非仅依赖 UniXNU serial log。

## 一次受控菜单复现方案（仅 `fastboot boot`）

设备操作必须由 Lead 在用户明确同意后执行；本步骤本身不执行设备命令，也不刷写
任何分区：

1. 先对待启动文件离线计算 SHA-256，必须等于固定历史镜像
   `f84337c7...985c`；同时保存 `boot.json` 与本记录中的 FD/DTB/ramdisk
   摘要。
2. 只使用 bootloader 临时启动：

   ```sh
   fastboot boot /absolute/path/to/boot.img
   ```

   禁止 `flash`、`fastboot reboot bootloader` 之外的持久写入，不替换 DTB、FD、
   BootShim、display 或 memory map。
3. 观察顺序：Mu logo/GOP → UniXNU logo/menu。若进入菜单，立即按输入键停止
   default countdown，记录画面（或文本 fallback）及选中项；不要让 builtin `exit`
   计时跑完，否则它会返回 firmware，随后 BDS 可能继续 BootOrder 并显示 no-OS。
4. 记录镜像 hash、设备 bootloader 返回、最后可见阶段、GOP/ConOut 状态；分别
   标记“历史用户观察”“本次 fastboot 观察”“未验证”。一次 `fastboot boot`
   成功只证明该临时启动路径，不能证明持久刷写或当前源码重建。
5. 若未见 UniXNU 菜单，不先改 BDS/APRIORI/ramdisk。先保存“无菜单”的精确阶段，
   再离线检查该镜像是否仍为固定 hash、FD 本体 GUID 是否一致、BootOrder/LoadImage
   证据是否存在；no-OS 只表示 Mu 的 `UnableToBoot` 收尾，不单独定位失败原因。

## 明确不纳入本次基线

- 不启用 OnyxBootOptions 或 board-local 新 BDS 注册实现。
- 不加入 QR logger、OnyxMap、runtime-FDT/x0 修复、RamDisk-first 实验。
- 不把当前 `/home/firefly/UniXNU/Mu-Silicium` checkout 的构建输出或后来
  `Build` 清单替代历史 FD 本体。
- 不在没有设备观察的情况下声称当前源码或新 image 已成功启动。
