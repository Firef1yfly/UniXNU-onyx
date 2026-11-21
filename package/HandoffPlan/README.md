# Handoff planning primitive — not installed in firmware

`HandoffPlan.c` is a freestanding C address-validation/planning primitive for future SEC integration. It does **not** implement memory preservation, create HOBs, map pages, dereference physical addresses or parse the complete FDT. No INF or firmware component selects it. A passing result is not an onyx boot result or allocation guarantee.

## Inputs and checks

The caller supplies an already-readable copy of the 40-byte FDT header, an independently established readable extent, validated initrd start/end, verified identity-mapped RAM spans, and every forbidden write/reclaim footprint. The helper rejects malformed header/block bounds, zero/reversed/overflow ranges, non-eight-byte-aligned FDT addresses, page-rounding overflow, unknown/uncovered pages, overlapping caller RAM spans, FDT/initrd page overlap and collisions with forbidden footprints. Results are published only on success; original inputs are not changed.

Whole input pages must fit one verified safe span; adjacent banks are not merged. Forbidden footprints can be unaligned. An exclusive endpoint of `2^64` is conservatively rejected to avoid representing it as an overflowing C integer. This is stricter than the Python ADT encoding boundary test and is deliberate for physical-page arithmetic.

The bounded header check is **not a complete FDT validator**: it does not walk all reservation entries or structure tokens, authenticate the source, or extract `/chosen` values. That must happen separately, from a buffer established safe to read. The helper trusts the caller's verified RAM and forbidden sets; omitted firmware/secure/allocator regions cannot be discovered magically.

## Why this is not yet an SEC patch

The local Mu flow writes memory before `SecMain`:

1. BootShim copies FD to its destination.
2. SEC assembly establishes and clears the fixed stack.
3. SEC C constructs the HOB arena, then MMU/translation tables and allocations.

Calling a C planner at step 3 cannot undo corruption at steps 1–2. Earlier collision guarantees or an early-stage validation path are required. The full known write footprints, including the complete chosen PrePi arena and decompression/driver allocation spaces, must be forbidden until a real ownership transition is implemented. Current board runtime addresses are not available; do not invent them to make a plan pass.

**An allocation HOB alone does not protect PrePi inputs.** The local PrePi allocator allocates pages by moving PHIT `EfiFreeMemoryTop` and allocates pool/HOB records by growing `EfiFreeMemoryBottom`; it does not search allocation HOBs for holes. A source buffer inside that arena can therefore be overwritten despite an allocation HOB naming it. Select a disjoint, verified PrePi arena before `HobConstructor`, or implement an allocator that truly excludes the buffers; do not pretend an arbitrary hole is protected by adding metadata afterward.

After a valid plan exists, actual integration must also establish correct MMU attributes and HOB ownership for the retained ranges, confirm DXE descriptor accounting, and prevent RamManager from treating them as free gaps. This requires additional reviewed code and measurements.

## Host verification

From the device checkout:

```sh
python3 -m unittest discover -s tests -p 'test_handoff_plan.py' -v
```

12 tests compile the real C implementation into a temporary shared library and execute it through ctypes using **synthetic** numeric physical addresses. Tests cover alignment, inaccessible pages, bad headers, boundaries, rounding, collisions, bad caller maps, failure-output preservation and both x86 host/freestanding AArch64 compilation. No fixture range is a measured onyx address.

The companion `fuzz_handoff.c` harness was compiled with Clang `-fsanitize=fuzzer,address,undefined -g -O1` and run for **100000 iterations**, seeded with a valid synthetic header and numeric addresses, `-max_len=88`. It exited 0 with no sanitizer findings (seed 4087607090). This checks memory/arithmetic robustness for that harness, not completeness of the firmware protocol or all possible inputs. Build outputs and corpus were temporary.

See [the firmware handoff audit](../../docs/UEFI-HANDOFF.md) and [runtime evidence checklist](../../docs/RUNTIME-MEMORY.md) before considering firmware integration.
