# Round 33 test plan

The previous EFI-map diagnostic boot used a historical payload and current runtime FDT, then black-screened without logs. Offline comparison shows the historical successful-looking artifact used a generic Tuna DTB with zero memory and a different firmware/kernel checkout. The difference is too large to infer a single failure stage.

The next device attempt must use one pinned combination:

1. Mu-Silicium tested commit and exact Binaries/onyx set;
2. temporary OnyxMapDxe FD built from that checkout;
3. current kernel and package from one UniXNU revision;
4. an ADT generated only after EFI map output, not Android `memory/reg` or synthetic RAM;
5. serial/QR capture ready before `fastboot boot`.

If EFI map capture cannot be obtained from a full payload, do not repeat black-screen attempts. Use the maintainer-tested artifact only for offline file-layout comparison, not as an unverified recovery image.
