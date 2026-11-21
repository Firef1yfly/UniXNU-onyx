/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include "HandoffPlan.h"

static uint32_t be32(const uint8_t *p) {
  return ((uint32_t)p[0]<<24) | ((uint32_t)p[1]<<16) | ((uint32_t)p[2]<<8) | p[3];
}
static int valid(ONYX_SPAN s) {
  return s.size != 0 && s.base <= UINT64_MAX - s.size;
}
static int overlap(ONYX_SPAN a, ONYX_SPAN b) {
  return a.base < b.base+b.size && b.base < a.base+a.size;
}
static int pages(ONYX_SPAN input, ONYX_SPAN *out) {
  uint64_t end, rounded;
  if (!valid(input)) return 0;
  end = input.base+input.size;
  if (end > UINT64_MAX - (ONYX_HANDOFF_PAGE-1)) return 0;
  rounded = (end+ONYX_HANDOFF_PAGE-1) & ~(ONYX_HANDOFF_PAGE-1);
  out->base = input.base & ~(ONYX_HANDOFF_PAGE-1);
  out->size = rounded-out->base;
  return valid(*out);
}
static int contained(ONYX_SPAN input, const ONYX_SPAN *ram, size_t count) {
  size_t i;
  for (i=0;i<count;i++)
    if (ram[i].base<=input.base && input.base+input.size<=ram[i].base+ram[i].size) return 1;
  return 0;
}
static int block_inside(uint32_t offset, uint32_t length, uint32_t total) {
  return offset>=40 && offset<=total && length<=total-offset;
}

ONYX_PLAN_STATUS OnyxPlanHandoff(
  const uint8_t *h, size_t header_bytes, uint64_t address,
  uint64_t readable_bytes, uint64_t start, uint64_t end,
  const ONYX_SPAN *ram, size_t ram_count,
  const ONYX_SPAN *forbidden, size_t forbidden_count,
  ONYX_HANDOFF_PLAN *output) {
  uint32_t total, structure, strings, reserve, version, compatible, str_size, struct_size;
  size_t i,j;
  ONYX_HANDOFF_PLAN plan = {{0,0},{0,0},0};
  ONYX_SPAN raw;
  if (!h || !output || !ram || ram_count==0 || ram_count>ONYX_HANDOFF_MAX_SPANS ||
      forbidden_count>ONYX_HANDOFF_MAX_SPANS || (forbidden_count && !forbidden) || header_bytes<40)
    return ONYX_PLAN_ARGUMENT;
  /* Do not dereference address: h is the already-readable header copy. */
  total=be32(h+4); structure=be32(h+8); strings=be32(h+12); reserve=be32(h+16);
  version=be32(h+20); compatible=be32(h+24); str_size=be32(h+32); struct_size=be32(h+36);
  if (be32(h)!=UINT32_C(0xd00dfeed) || total<40 || total>ONYX_HANDOFF_MAX_FDT ||
      version!=17 || compatible>17 || !struct_size ||
      (structure&3) || (reserve&7) ||
      !block_inside(structure,struct_size,total) || !block_inside(strings,str_size,total) ||
      !block_inside(reserve,16,total) ||
      ((uint64_t)structure < (uint64_t)strings+str_size && (uint64_t)strings < (uint64_t)structure+struct_size) ||
      ((uint64_t)reserve < (uint64_t)structure+struct_size && (uint64_t)structure < (uint64_t)reserve+16) ||
      ((uint64_t)reserve < (uint64_t)strings+str_size && (uint64_t)strings < (uint64_t)reserve+16))
    return ONYX_PLAN_FDT_HEADER;
  if (!address || (address&7) || readable_bytes<total || start==0 || end<=start)
    return ONYX_PLAN_RANGE;
  for (i=0;i<ram_count;i++) {
    if (!valid(ram[i]) || (ram[i].base&(ONYX_HANDOFF_PAGE-1)) || (ram[i].size&(ONYX_HANDOFF_PAGE-1)))
      return ONYX_PLAN_ARGUMENT;
    for (j=0;j<i;j++) if (overlap(ram[i],ram[j])) return ONYX_PLAN_ARGUMENT;
  }
  for (i=0;i<forbidden_count;i++) if (!valid(forbidden[i])) return ONYX_PLAN_ARGUMENT;
  raw.base=address; raw.size=total;
  if (!pages(raw,&plan.fdt_pages)) return ONYX_PLAN_RANGE;
  raw.base=start; raw.size=end-start;
  if (!pages(raw,&plan.initrd_pages)) return ONYX_PLAN_RANGE;
  if (!contained(plan.fdt_pages,ram,ram_count) || !contained(plan.initrd_pages,ram,ram_count))
    return ONYX_PLAN_NOT_ACCESSIBLE;
  if (overlap(plan.fdt_pages,plan.initrd_pages)) return ONYX_PLAN_COLLISION;
  for (i=0;i<forbidden_count;i++)
    if (overlap(plan.fdt_pages,forbidden[i]) || overlap(plan.initrd_pages,forbidden[i]))
      return ONYX_PLAN_COLLISION;
  plan.fdt_bytes=total;
  *output=plan;
  return ONYX_PLAN_OK;
}
