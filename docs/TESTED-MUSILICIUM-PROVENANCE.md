# Tested Mu-Silicium integration provenance

The maintainer reports that their `Firef1yfly/Mu-Silicium` files have been tested on onyx to reach the UniXNU directory. Local evidence identifies:

- repository remote: `https://github.com/Firef1yfly/Mu-Silicium.git`
- tested local commit: `f77f9457b82f4a1dd33a305ab6ff12591347d416`
- parent tested integration commit: `664c841260773a369f758d7a27baa3494a59827f`
- public `main` remote currently points to `664c841260773a369f758d7a27baa3494a59827f`; the local f77f commit adds backup files and the same active source path remains under review.

The tested integration includes `UniXNURamDiskDxe`, `UniXNUDxe`, `UniXNU`, DarwinBoot, DiskIo, Partition and FAT in the onyx DSC/FDF. The tested repository also has `Resources/Configs/onyx.toml`, onyx binaries and the x0-to-HOB SEC change. However, the current active BootShim still forces the appended DTB and does not match the candidate header/x0 patch used in our temporary diagnostic build. The maintainer's “reaches the UniXNU directory” observation therefore proves the tested repository/filesystem integration path, not that the current candidate source or a newly built full iOS payload boots.

The direct package audit is recorded in [Mu-Silicium onyx audit](MUSILICIUM-ONYX-AUDIT.md), including exact remote-main file hashes and the deviations required for current diagnostics.

Do not mix the tested f77f firmware binary set, the current main commit, and the candidate BootShim patch without recording the exact combination. Future reproductions should pin the tested commit, list every binary source/hash, build the payload from the same UniXNU tree, and capture the exact boot-image hash before device testing.
