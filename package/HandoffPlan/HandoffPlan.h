/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Host-tested planning primitive only; NOT integrated into SEC.
 * This interface performs no physical reads, allocations, MMU changes or HOB writes.
 */
#ifndef ONYX_HANDOFF_PLAN_H
#define ONYX_HANDOFF_PLAN_H
#include <stddef.h>
#include <stdint.h>

#define ONYX_HANDOFF_PAGE UINT64_C(4096)
#define ONYX_HANDOFF_MAX_FDT UINT64_C(16777216)
#define ONYX_HANDOFF_MAX_SPANS 128

typedef struct { uint64_t base, size; } ONYX_SPAN;
typedef struct { ONYX_SPAN fdt_pages, initrd_pages; uint32_t fdt_bytes; } ONYX_HANDOFF_PLAN;
typedef enum {
  ONYX_PLAN_OK = 0, ONYX_PLAN_ARGUMENT, ONYX_PLAN_FDT_HEADER,
  ONYX_PLAN_RANGE, ONYX_PLAN_NOT_ACCESSIBLE, ONYX_PLAN_COLLISION
} ONYX_PLAN_STATUS;

/* header points to a caller-owned copy of >=40 readable bytes, NOT fdt_address.
 * readable_bytes bounds bytes from fdt_address that the caller has independently
 * established as safe to read. This is not inferred from the FDT itself.
 * initrd_start/end must come from checked /chosen 32/64-bit big-endian values.
 * This helper validates only copied header fields, not the full token stream or
 * memreserve list. A separate bounded parser must validate the whole FDT first.
 * Calling this from SecMain is TOO LATE to prevent earlier FD/stack overwrites;
 * it must be preceded by verified early-stage ownership/collision guarantees.
 * verified_ram contains only caller-verified, identity-mapped RAM usable for
 * retaining input buffers at THIS phase (not raw memory node marketing ranges).
 * forbidden contains every boot-time write/reclaim footprint: FD relocation,
 * stack clearing, HOB/PrePi heap, translation tables, decompression/driver heaps,
 * secure/firmware carveouts and source allocations that must remain untouched.
 * Whole rounded pages must fit ONE verified span and avoid all forbidden spans.
 * Adjacent safe spans are intentionally not coalesced. End==2^64 is rejected.
 * No output is returned on failure. Caller-owned buffers, span arrays and output
 * must be valid for their declared sizes and must not alias each other.
 * Success is a plan, not an allocation or proof
 * that its input evidence is genuine. The caller must reserve/map BEFORE writes.
 */
ONYX_PLAN_STATUS OnyxPlanHandoff(
  const uint8_t *header, size_t header_bytes, uint64_t fdt_address,
  uint64_t readable_bytes, uint64_t initrd_start, uint64_t initrd_end,
  const ONYX_SPAN *verified_ram, size_t ram_count,
  const ONYX_SPAN *forbidden, size_t forbidden_count,
  ONYX_HANDOFF_PLAN *output);
#endif
