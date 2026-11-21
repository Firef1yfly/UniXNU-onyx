# onyx EFI/RAM 内存报告 exporter 方案（只读设计）

> 状态：设计方案，未修改固件源码，未编译，未操作设备，未选择任何 ADT/DRAM 范围。
> 本文只为后续一次性诊断构建提供接口和时序；它不是硬件验证报告。

## 1. 目标和硬边界

目标是从**同一次 onyx 临时启动**取得两个原始事实：

1. UEFI `GetMemoryMap()` 的完整、带 descriptor stride 的快照；
2. Qualcomm `EFI_RAMPARTITION_PROTOCOL` 的完整 `Base/AvailableLength` 表。

同时记录能把快照绑定到这次启动的 FDT/initrd/FD 身份。主机用现有严格解析器
[`scripts/parse-uefi-memory-report.py`](../../scripts/parse-uefi-memory-report.py) 验证后，
才可把它作为后续讨论的输入。

以下内容明确不属于 exporter：

- 不把 Android `/proc/iomem`、Linux `memory/reg`、peridot/luming 数值转成 EFI map；
- 不把 RAM partition 自动改写成 `EfiConventionalMemory`，不选 ADT 的 DRAM range；
- 不在 SEC/PrePi 创建 HOB、保留区、页表或所有权转移；
- 不调用 `ExitBootServices()`，不把 `MapKey` 说成 XNU/DarwinBoot 交接证明；
- 不依赖 GOP、DisplayDxe、SimpleFb、二维码或 XNU 菜单才能产生原始 map；
- 不写分区、不刷写、不假设任何一次黑屏达到了 DXE 或 BDS。

## 2. 现有代码审计结论

### 2.1 当前 OnyxMapDxe 不能作为最终 exporter

[`package/OnyxMapDxe/OnyxMapDxe.c`](../../package/OnyxMapDxe/OnyxMapDxe.c#L1-L5)
已声明它只是诊断快照，临时 pool 分配会改变观察到的 map，且未做 handoff
reservation。其 EFI map 路径（约 L17-L64）是有界重试并检查 stride、bytes、版本和
地址溢出；RAM 路径（约 L66-L110）使用 `LocateProtocol()` 和两次
`GetRamPartitions()`，并限制 4096 项。这些防护可复用为行为要求，但它把结果无限
`DEBUG` 行输出，缺少严格 JSON、完整性校验、截断检测和可靠传输。

`OnyxMapDxe.inf` 的 `TRUE` DEPEX 也不能证明它在 `RamManagerDxe` 后执行；FDF 中的
列出顺序不是 dispatch 完成证明。协议缺失必须报告失败，不能当作空表。

### 2.2 Mu 的 RAM 协议 ABI 和时序

固定参考为 Mu-Silicium 的
`Silicon/Qualcomm/QcomPkg/Include/Protocol/EFIRamPartition.h`：

- 协议 revision 是 `0x10002`；
- `RamPartitionEntry` 只有 `UINT64 Base` 和 `UINT64 AvailableLength`；
- `GetRamPartitions(This, Entries, IN OUT UINT32 *Count)` 以
  `EFI_BUFFER_TOO_SMALL` 返回所需数量；
- 协议还提供 preloaded image 表，但 v1 report 不纳入它，避免把不同 ABI 混入
  RAM range。

`Silicon/Qualcomm/QcomPkg/Library/RamManagerLib/RamManager.c` 当前把协议表复制成
`EFI_MEMORY_RANGE`，并可能把数量缩小为 `UINT8`；exporter 不得沿用该窄化，必须保留
原始 `UINT32` count 和 revision。

`Silicon/Silicium/SiliciumPkg/Drivers/RamManagerDxe/RamManager.c` 会先取得 EFI map，
再把 RAM protocol range 中的间隙映射为 `EfiConventionalMemory`。因此诊断模块必须
在 RAM manager 完成后取 BDS/DXE 快照，或者用 EndOfDxe 事件确保所有 DXE dispatch 已
结束；不能仅凭 FDF 顺序推断 map 已稳定。

### 2.3 FDT/initrd/FD 只能作为同次启动关联

Mu `Sec.c` 将入口 x0 保存到 GUID HOB
`DAEE82E6-8090-4E72-BFB9-78C13CD4E359`；`UniXNURamDiskDxe.c` 读取该 HOB，检查
FDT header，再从 `/chosen/linux,initrd-start/end` 发布只读 Block I/O。
exporter 应读取这一个 runtime FDT HOB，而不是读取 boot.img 追加的静态 DTB。
FDT、initrd 和 FD association 缺失或无法安全读取时，整份报告失败；不能用静态
Android DTB 补字段。

### 2.4 AdvancedLogger/QR 不是原始 map 的前置条件

现有 QR 模块
[`unixnu/package/UniXNUPkg/Driver/AdvancedLogDxe/AdvancedLogDxe.c`](../../../unixnu/package/UniXNUPkg/Driver/AdvancedLogDxe/AdvancedLogDxe.c#L409-L461)
会动态收集日志并用 `ReallocatePool()` 增长缓冲；没有日志时明确返回
`EFI_NOT_FOUND`（约 L495-L507）。它依赖 AdvancedLogger producer、日志缓冲、GOP 和
菜单插件。QR OneSend 每块 720 字节且有 CRC，但显示端、相机和 GOP 任一缺失都会使
传输不可用。因此 QR 只能是 serial 失败后的复现通道，不能用来证明 DXE 已运行，更
不能作为唯一 map 捕获方式。

## 3. 最小 exporter 形态（未来临时模块）

建议新建**一个**临时 `OnyxMemoryReportDxe`（DXE_DRIVER），只运行一次；不修改
现有 `OnyxMapDxe`，不把它并入正式板级驱动。模块只需要：

- `UefiBootServicesTableLib`、`MemoryAllocationLib`、`BaseMemoryLib`、`PrintLib`；
- `RamPartition` protocol；
- Mu runtime FDT HOB/`FdtLib`；
- 固件 FD 的 `PcdFdBaseAddress/PcdFdSize`；
- 若要填入 FD/FDT SHA-256，使用已有 BaseCryptLib SHA-256 接口；没有该库时应
  **fail closed**，不能写零哈希或声明 host 代算；
- 一个 bounded JSON writer 和一个 bounded frame writer。二者不能在输出过程中
  `AllocatePool()`、`LocateHandleBuffer()` 或调用会分配的 Boot Services。

使用 `gEfiEndOfDxeEventGroupGuid` 注册一次性事件是首选时序：DXE 驱动已 dispatch，
RamManager 和厂商协议应已完成；事件回调中先验证 protocol/FDT，然后完成所有需要
分配的准备，最后取得 map。若该事件组在本 Mu 版本不可用，备选是明确的 DXE/BDS
一次性应用，报告 `capture.stage = bds_snapshot`；不得把自动 `TRUE` DEPEX 当成时序
保证。

模块不要求 GOP，因此显示黑屏时仍可尝试 serial/变量捕获。`EndOfDxe` 只表示 DXE
阶段边界，不表示 `ExitBootServices` 成功。

## 4. 严格报告 contract 的实现映射

主机 contract 见 [`docs/bringup/memory-report-format.md`](memory-report-format.md)。
exporter 必须产生一个完整 root object，未知字段不应写入：

- `schema = "onyx-uefi-memory-report"`、`schema_version = 1`、`device = "onyx"`；
- `capture.kind = "uefi_get_memory_map"`；stage 为 `dxe_snapshot`、`bds_snapshot`
  或 `pre_exit_boot_services`，本方案不调用 ExitBootServices，故通常为前两者；
- `exit_boot_services = false`；
- `memory_map.descriptor_version`、`descriptor_size`、`descriptor_count`、
  `map_bytes` 来自**最后一次成功的同一 GetMemoryMap 调用**；descriptor 原始
  stride 不得硬编码成 48 字节；
- 每个 descriptor 保留 `type`、`physical_start`、`virtual_start`、
  `number_of_pages`、`attribute`，并由 writer 计算 `end`。类型必须为 0..13；不
  合法、零页、未对齐或 64 位溢出即失败；
- `ram_partitions.protocol_revision = "0x10002"`，count 为 UINT32，entry 只含
  `base`、`available_length` 和可选 computed `end`；空、重叠、溢出、第二次 count
  不一致、protocol 缺失或调用失败均是失败，不是空列表；
- `associations.fdt` 必须来自 `uefi_runtime_fdt`，带实际 bytes/SHA-256；
  `associations.initrd` 必须来自 `uefi_runtime_fdt_chosen` 的半开区间；
  `associations.fd` 带 `PcdFdBaseAddress`、`PcdFdSize`、实际 SHA-256，source 为
  `mu_uefi_fd`；
- 所有地址/长度使用明确的 `0x` 十六进制字符串，count/size 使用 JSON integer；
  不输出 serial、IMEI、Android、`/proc/iomem`、luming 等来源文本。

### 单一报告对象 / 单一变量 fallback

实现上只允许一个不可分割的 `OnyxMemoryReport` 报告对象。若选择 UEFI variable
作为无 serial fallback，使用一个固定 vendor GUID + `L"OnyxMemoryReport"`，只在
**完整 JSON 已构造并通过本地长度/字段检查后**一次 `SetVariable()`；不可分块写
多个变量，不可先写半成品再覆盖。变量应只设置 BootService-access、非持久化属性
（具体属性以目标 Mu 的 variable policy 为准），并在报告中标记 `transport=variable`
而不是误称为设备持久证据。

变量不是首选：SetVariable 可能改变 EFI map、受 variable store 容量/策略限制，且
重启后可能消失。它只能保存已经完成的 map 快照；不得在写变量后重新声称拿到了
ExitBootServices map。若 variable 写失败，保留 serial/QR fallback；若所有传输都
失败，则不输出“空报告”，而输出有界失败状态并返回 BDS。

## 5. 无歧义的调用顺序

为避免最终 map 被 exporter 自己的序列化分配污染，同时诚实记录必要的诊断分配，
采用如下顺序：

1. 注册一次性 EndOfDxe 回调；回调开始后拒绝重入。
2. `LocateProtocol(gEfiRamPartitionProtocolGuid)`；检查 protocol 指针和
   `GetRamPartitions`。读取 revision，但不要把 revision 不匹配静默转换。
3. 第一次 `GetRamPartitions(NULL, &count)`，只接受 `EFI_BUFFER_TOO_SMALL` 或目标
   ABI 明确允许的成功返回；检查 `1 <= count <= 4096`。预先分配固定大小 entries
   buffer后第二次调用，要求成功、`returned_count == requested_count`，逐项检查
   overflow/overlap；count 变化就丢弃并有限重试，不能把变化截断。
4. 从 entry HOB 读取 runtime FDT header；先做 bounded header/total-size/block
   检查，再在已验证可读范围内读取 `/chosen`；提取 initrd start/end。计算 FDT
   和 FD SHA-256。任何读范围、hash 或 chosen 属性失败都停止。
5. 为 JSON 和 transport frame 预分配固定上限 buffer；为 map 做 size probe：
   `GetMemoryMap(&Bytes, NULL, &Key, &Stride, &Version)`。接受
   `EFI_BUFFER_TOO_SMALL`，检查 `Stride >= 40`、8 字节倍数、`Bytes` 不溢出；按
   `Bytes + 2*Stride`（并受总上限约束）分配 map buffer。此分配会改变 map，故只把
   下一次成功调用当作诊断 snapshot。
6. 第二次 `GetMemoryMap()`，将 `MapBytes/MapKey/DescriptorSize/Version` 从这一次
   调用一起保存；若仍 `EFI_BUFFER_TOO_SMALL`，最多 4 次重新分配并重试，最终一次
   调用后不得再使用会分配的 Boot Services。MapKey 只作内部调试字段，不能写入
   v1 public report。
7. 逐 stride 遍历 map；若 bytes 非 stride 整数、version 非 1、descriptor type/
   range/attribute 不符合 contract，整份报告失败。不要排序或合并 descriptor；顺序
   可保留固件顺序，主机 parser 会检查物理重叠。
8. 用固定 writer 将 JSON 写入已分配 buffer；writer 溢出、字段遗漏、UTF-8/转义
   失败即失败。writer 不调用 Boot Services、不 `DEBUG` 大量文本。serialize 后做
   长度和 root 字段自检，确保没有截断。
9. 先尝试可靠传输（见下一节）。成功标准是 host 收到完整 framing、CRC/长度校验、
   reassembly 后 strict parser 通过；失败不降级为“部分有效 map”。
10. 传输结束后仅释放临时 buffer并返回；不得调用 `ExitBootServices`、重启或写盘。

注意：不能让第 5 步之后的 `SetVariable`、日志初始化、文件系统连接或 QR GOP
连接参与第 6 步前的 map 采样。若 transport 必须分配，全部预留在第 5 步；否则
报告明确是已经完成准备后的 DXE snapshot，而不是“无扰动初始 map”。

## 6. 有界失败和资源上限

建议第一版采用以下 hard caps（超过即失败并报告 `E2BIG`，绝不截断）：

- RAM entries：4096（与现有 OnyxMapDxe 上限一致）；
- EFI descriptors：4096；strict host parser 允许到 65536，但 exporter 的较小上限
  是安全诊断策略，不是对硬件数量的推断；
- descriptor stride：40..4096，8 字节倍数；raw map bytes 不超过 16 MiB；
- canonical JSON：不超过 4 MiB；单 frame payload 不超过 512 字节；
- FDT total size：不超过 4 MiB；FD hash 分块读，不分配 FD 大小的副本；
- `GetMemoryMap` 和 `GetRamPartitions` 各最多 4 次有效重试；
- serial 单帧写最多固定次数，任何 partial write/timeout 都使该传输失败；
- 任何 count/size/地址乘法均先做 UINT64/UINTN overflow 检查。

报告必须包含一个完整的 `status=ok` 语义（该字段若不在 v1 contract 则不要写入
JSON；可放在 framing 状态中）。失败 framing 只包含阶段、EFI status、attempt 和
失败码，不伪装成 contract JSON。失败后不继续使用不完整 map，不将缺失 protocol
当零 partition，不将缺失 FDT 当静态 DTB。

## 7. 可靠 framing 和传输优先级

### 7.1 统一 framing

JSON 之外使用 ASCII、逐行、可重同步 framing，避免 UART/QR 丢字节后把后续数据
拼进错误 JSON。建议格式（字段均 ASCII）：

```text
ONYXMEM1 BEGIN id=<hex> bytes=<decimal> frames=<decimal> crc=<hex8>\n
ONYXMEM1 DATA id=<hex> seq=<decimal>/<decimal> len=<decimal> crc=<hex8> data=<hex>\n
ONYXMEM1 END id=<hex> bytes=<decimal> frames=<decimal> crc=<hex8>\n
```

`data` 是 JSON 原始 UTF-8 的小写 hex，不是折行文本；每一行长度固定受限。每个
DATA 做 CRC32，BEGIN/END 的 bytes/frame count/全量 CRC 必须一致。host 只接受
BEGIN→所有 seq 恰好一次→END 的完整会话；重复帧可去重，缺帧/CRC/长度/id 不一致
则整会话丢弃。host reassemble 后仍必须运行 strict parser；CRC 不是 SHA-256 或
UEFI provenance 的替代品。若可用 SHA-256，BEGIN/END 另带 JSON SHA-256；否则 host
对重组 JSON 计算并记录。

### 7.2 优先级

1. **直接 serial protocol（首选）**：不依赖 GOP/菜单/QR。预分配 512B frame，调用
   `EFI_SERIAL_IO_PROTOCOL.Write()`，检查 `BufferSize` 回写值；partial write 固定
   重试后失败。每行带 newline 和重同步 magic，主机按 BEGIN/END 保存原始文本。
2. **单一 volatile UEFI variable（备用）**：仅保存完整 JSON（或完整 framed report，
   取决于 variable size），一次写入；写后从变量读取回读并校验长度/CRC。失败不重试
   无限次。变量容量不足时不可分块变量伪造成功。
3. **AdvancedLogger→AdvancedLogDxe OneSend/QR（最后的显示通道）**：仅在已有
   AdvancedLogger producer、非空日志、GOP/ConOut 和第二台相机全部确认时启用。不能
   让 QR 依赖 Tools 菜单进入，因为这会把菜单/BDS/GOP 问题和 map 报告混在一起。
   由 logger 写入有限 framing 行；AdvancedLogDxe 本身的 720B OneSend 分块/CRC 只
   是第二层校验。
4. **文件系统/分区写入明确禁用**：FAT、DiskIo、PartitionDxe 或 userdata 可能
   尚未连接；写盘还会改变用户数据并引入持久化恢复风险，不适合作为首次 map 证据。

### 7.3 恢复和判定

- serial unavailable：不把 DEBUG 缓冲输出当成功，尝试 variable；两者均失败才
  尝试 QR（若已预检）；
- 任何阶段失败：输出有限的一行 `ONYXMEM1 FAIL ...`（若 transport 可用），返回
  `EFI_ABORTED`/原始 EFI status 到 BDS；不 reset、不 flash、不改 slot；
- 设备黑屏但 host 没拿到 BEGIN+END：结果是“无报告”，不是零内存，也不是 EFI
  map 不可用；停止复测并保留镜像 hash；
- host parser 拒绝：保留原始 framing 和 stderr，修 exporter/contract 后再试；
  不手工编辑数值让 parser 通过；
- 一次完整报告只允许一个 capture stage；serial、variable、QR 取得的副本必须
  hash 相同，否则标为不一致并丢弃，不能挑选“看起来较好”的 map。

## 8. 后续验收门槛（仍不是本次实施）

1. 在 host 上为 serializer/framer 做 synthetic descriptor、count mismatch、
   descriptor stride、partial UART、duplicate/missing frame 和 JSON overflow 测试；
2. 在隔离 Mu 树仅加入 exporter，检查 FFS/DEPEX，确认没有 `OnyxMapDxe`、QR、BootShim、
   DisplayDxe、ADT 或 board.toml 变化；
3. 离线检查同批次 FD、BootShim、DTB、payload 和 exporter hash；
4. 用户明确授权后才 `fastboot boot`，先准备 serial/QR 接收端；不 flash；
5. 只有 parser 通过、capture provenance 正确且原始 framing 保存后，才把 task-8
   视为“取得 map/RAM protocol 证据”；这仍不等于 safe-to-boot 或 ADT 可用。

## 9. 本轮结论

- 现有 OnyxMapDxe 的边界/溢出检查可作为参考，但其 DEBUG 输出、临时分配和 TRUE
  DEPEX 不满足严格报告；
- Mu RAM protocol 的确切 ABI 已核对，count 必须保持 UINT32，缺失/变化必须失败；
- EndOfDxe + 预分配 + 最后一次 GetMemoryMap 是最小且可解释的 DXE snapshot 时序；
- serial 是不依赖 GOP 的首选，单变量是容量有限的备用，QR 是有明确依赖的最后通道，
  文件系统/分区写入禁用；
- 本文没有任何真实 EFI map、RAM partition、可用 DRAM 或 ADT 结论。
