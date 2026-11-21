# Round 33 historical artifact comparison

The older local onyx boot artifact uses an appended DTB with generic identity and zero memory:

```text
model: Qualcomm Technologies, Inc. Tuna SoC
compatible: qcom,tuna
qcom,msm-id: <655 0x10000>
qcom,board-id: <0 0>
/memory/reg: <0 0 0 0>
DTB bytes: 879313
sha256: 6379d64c8472c7c4c2d9d225803bebe33b8bd2c14cb73c6b329a8a5458dd6f23
```

The current runtime FDT is materially different:

```text
model: Qualcomm Technologies, Inc. Onyx based on SM8735
compatible: qcom,tuna-mtp, qcom,tuna, qcom,tunap-mtp, qcom,tunap, qcom,mtp
qcom,msm-id: <681 0x10000>, <655 0x10000>
qcom,board-id: <8 0>
/memory/reg: 22 fragmented tuples including a zero-size tuple
DTB bytes: 847177
sha256: 3b90da7e20c3bbde0e2663726e95ef66396260200aa2b2452fcb076d87794365
```

The old artifact's successful “reaches EFI/UniXNU” report therefore does not prove that its static zero-memory DTB can boot the current runtime, nor that the current full kernel/payload can use it. The most important variable difference is the DTB/BootShim/FDT handoff, not FAT directory layout. Never substitute the old DTB or synthetic memory for a real ADT input.
