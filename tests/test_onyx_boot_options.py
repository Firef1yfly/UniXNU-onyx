#!/usr/bin/env python3
"""Host tests for the dormant OnyxBootOptions C provider.

The tests compile the provider with a tiny mock of the real Mu library ABI.
They intentionally do not build EDK II, create an FV, integrate the library,
or touch a device.
"""
from __future__ import annotations

import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "package/OnyxBootOptions/OnyxBootOptions.c"

MOCK = r'''
#include <stdint.h>
#include <stddef.h>
typedef uint16_t CHAR16; typedef uint8_t UINT8; typedef uint32_t UINT32;
typedef struct { uint8_t b[16]; } EFI_GUID;
typedef struct { CHAR16 *AppName; EFI_GUID *AppGuid; UINT32 LoadAttribute; } EFI_PLATFORM_BOOT_OPTION;
#define OUT
#define VOID void
#define LOAD_OPTION_ACTIVE 1U
#define LOAD_OPTION_HIDDEN 8U
#define DEBUG(x) ((void)0)
static int fail_alloc;
static int missing_unixnu;
static int missing_mass;
static int frees;
static void *AllocateZeroPool(size_t n) { if (fail_alloc) return NULL; static unsigned char arena[256]; if (n > sizeof(arena)) return NULL; for (size_t i=0;i<n;i++) arena[i]=0; return arena; }
static void FreePool(void *p) { if (p) frees++; }
static EFI_GUID unixnu = {{1}}, mass = {{2}};
#define FixedPcdGetPtr(x) ((x) == PcdUniXNUApplicationFile ? (missing_unixnu ? NULL : &unixnu) : (missing_mass ? NULL : &mass))
#define PcdUniXNUApplicationFile 1
#define PcdMassStorageFile 2
'''


class OnyxBootOptionsHost(unittest.TestCase):
    def compile_and_run(self, body: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            inc = tmp / "include"
            (inc / "Library").mkdir(parents=True)
            (inc / "Library" / "PlatformBootOptionsLib.h").write_text(r'''
#ifndef PLATFORM_BOOT_OPTIONS_LIB_H
#define PLATFORM_BOOT_OPTIONS_LIB_H
#include <stdint.h>
typedef struct { uint16_t *AppName; struct EFI_GUID *AppGuid; uint32_t LoadAttribute; } EFI_PLATFORM_BOOT_OPTION;
void GetPlatformBootOptions(EFI_PLATFORM_BOOT_OPTION **, uint8_t *);
#endif
''', encoding="utf-8")
            (inc / "Uefi.h").write_text(r'''
#include <stdint.h>
typedef uint16_t CHAR16; typedef uint8_t UINT8; typedef uint32_t UINT32;
typedef struct EFI_GUID { uint8_t b[16]; } EFI_GUID;
#define OUT
#define VOID void
#define LOAD_OPTION_ACTIVE 1U
#define LOAD_OPTION_HIDDEN 8U
#define L"x" ((CHAR16[]){'x',0})
'''.replace('#define L"x" ((CHAR16[]){\'x\',0})\n', ''), encoding="utf-8")
            (inc / "Library" / "DebugLib.h").write_text("#define DEBUG(x) ((void)0)\n", encoding="utf-8")
            (inc / "Library" / "MemoryAllocationLib.h").write_text("#include <stddef.h>\nvoid *AllocateZeroPool(size_t); void FreePool(void *);\n", encoding="utf-8")
            (inc / "Library" / "PcdLib.h").write_text(r'''
extern int fail_alloc, missing_unixnu, missing_mass, frees;
extern struct EFI_GUID unixnu, mass;
#define PcdUniXNUApplicationFile 1
#define PcdMassStorageFile 2
#define FixedPcdGetPtr(x) ((x) == PcdUniXNUApplicationFile ? (missing_unixnu ? (void *)0 : &unixnu) : (missing_mass ? (void *)0 : &mass))
''', encoding="utf-8")
            harness = tmp / "harness.c"
            harness.write_text(r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <Uefi.h>
#include <Library/PlatformBootOptionsLib.h>
struct EFI_GUID unixnu = {{1}}, mass = {{2}};
int fail_alloc, missing_unixnu, missing_mass, frees;
void *AllocateZeroPool(size_t n) { static unsigned char arena[256]; if (fail_alloc || n > sizeof(arena)) return NULL; memset(arena, 0, n); return arena; }
void FreePool(void *p) { if (p) frees++; }
'''+body, encoding="utf-8")
            exe = tmp / "test"
            subprocess.run(["clang", "-std=c11", "-fshort-wchar", "-Wall", "-Wextra", "-Werror", "-I", inc, SOURCE, harness, "-o", exe], check=True, capture_output=True)
            return subprocess.check_output([exe], text=True)

    def test_success_preserves_mass_storage_and_active_unixnu(self):
        out = self.compile_and_run(r'''
#include <stdio.h>
int main(void) { EFI_PLATFORM_BOOT_OPTION *o; UINT8 n; GetPlatformBootOptions(&o,&n);
  if (!o || n != 2 || o[0].AppGuid != &unixnu || o[1].AppGuid != &mass ||
      o[0].LoadAttribute != LOAD_OPTION_ACTIVE || o[1].LoadAttribute != LOAD_OPTION_HIDDEN ||
      o[0].AppName[0] != 'U' || o[1].AppName[0] != 'M') return 1;
  puts("success"); return 0; }
''')
        self.assertEqual(out.strip(), "success")

    def test_null_outputs_are_noop(self):
        self.compile_and_run(r'''
int main(void) { EFI_PLATFORM_BOOT_OPTION *o = (void *)1; UINT8 n=9;
  GetPlatformBootOptions(NULL,&n); GetPlatformBootOptions(&o,NULL); return o==(void *)1 && n==9 ? 0 : 1; }
''')

    def test_allocate_failure_does_not_publish(self):
        self.compile_and_run(r'''
int main(void) { EFI_PLATFORM_BOOT_OPTION *o = (void *)1; UINT8 n=9; fail_alloc=1;
  GetPlatformBootOptions(&o,&n); return o==NULL && n==0 && frees==0 ? 0 : 1; }
''')

    def test_partial_pcd_failure_frees_and_does_not_publish(self):
        for which in ("missing_unixnu", "missing_mass"):
            with self.subTest(which=which):
                self.compile_and_run(f'''
int main(void) {{ EFI_PLATFORM_BOOT_OPTION *o = (void *)1; UINT8 n=9; {which}=1;
  GetPlatformBootOptions(&o,&n); return o==NULL && n==0 && frees==1 ? 0 : 1; }}
''')


if __name__ == "__main__":
    unittest.main()
