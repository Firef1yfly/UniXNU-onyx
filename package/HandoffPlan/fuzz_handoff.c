/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * libFuzzer/ASan/UBSan host harness. Numeric physical addresses are never read.
 */
#include "HandoffPlan.h"
#include <string.h>

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
  uint64_t args[6];
  ONYX_SPAN ram[2] = {{UINT64_C(0x80000000),UINT64_C(0x10000000)},
                      {UINT64_C(0x100000000),UINT64_C(0x10000000)}};
  ONYX_SPAN blocked[1] = {{UINT64_C(0x88000000),UINT64_C(0x100000)}};
  ONYX_HANDOFF_PLAN plan;
  if (size<40+sizeof(args)) return 0;
  memcpy(args,data+40,sizeof(args));
  (void)OnyxPlanHandoff(data,40,args[0],args[1],args[2],args[3],ram,2,blocked,1,&plan);
  blocked[0].base=args[4]; blocked[0].size=args[5];
  (void)OnyxPlanHandoff(data,40,args[0],args[1],args[2],args[3],ram,2,blocked,1,&plan);
  return 0;
}
