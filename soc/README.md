# Minimal SM8735 profile (vendored development source)

This is the local, device-versioned start of shared SM8735 support. It is not a published or hardware-qualified SoC repository. The old absolute `file:///home/firefly/UniXNU-sm8735-common` dependency is no longer used.

## Evidence

Both base DTBs in the [current Android 17 archive](../docs/CURRENT-ANDROID17.md), and the [historical Android 16 set](../docs/STOCK-IMAGES.md), agree on CPU affinities, GIC ranges and stride, timer frequency/interrupts, and PSCI conduit. The offline onyx overlay merges preserve those facts. Firmware selection between base 0 (655) and base 1 (681), CPU boot MPIDR, runtime memory and hardware interrupt behavior remain unobserved.

Bindings were adapted to UniXNU: top-level PSCI, explicit identity bus ranges, `/cpus/timebase-frequency`, and GIC `unixnu,adt-name="intc"`. The name and two translated register tuples match the pinned [ArmCpu implementation](https://github.com/UniXNU/ArmCpu/blob/93a5030c5d983d0ef90f0fca93879d6e36ad1ba8/ArmCpu.cpp). GIC `redistributor-stride=0x40000` comes from both stock blobs, not SM8550 assumptions. The generic driver uses virtual timer INTID 27, consistent with the stock timer tuple containing PPI 11.

## Limits

All CPUs default disabled. The device enables only the first candidate affinity; this is a bring-up policy and not proof of firmware boot affinity. No microarchitecture/cluster split, DRAM geometry, full reservation map, UFS, display, touch, GPU, power operations or firmware binaries are implemented here. No SM8550 platform code is copied. Do not enable DMA or boot this description without resolving the board gates.

Run offline profile/DTB checks from the device checkout; see [the device README](../README.md). The board deliberately retains zero DRAM and `example=true`. Compilation and profile parsing are host integration checks only.
