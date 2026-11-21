"""Offline BootShim source/compile regression tests; not a firmware boot test."""
import importlib.util
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import tomllib
import unittest

DEVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEVICE.parent / 'unixnu/scripts'))
from unixnu.bootimg import compile_shim

# Only the reviewed source context needed for applying the patch. This fixture
# reproduces the local Mu-Silicium source bug; it is not a replacement firmware.
BASELINE = '''_Head:
  adr   x1, _Payload    /* Set _Entry address */
  b     _Start          /* Jump to the real code */

#if REQUIRES_KERNEL_HEADER == 1
_StackBase:
  .quad FD_BASE         /* Text Offset */

_StackSize:
  .quad FD_SIZE         /* Image Size */
  .quad 0               /* Flags */
  .quad 0               /* Reserved */
  .quad 0               /* Reserved */
  .quad 0               /* Reserved */
  .ascii "ARM\\x64"      /* ARM64 Magic */
  .long 0               /* Reserved */
#endif

_Start:
  /* Unconditionally use the appended DTB at _Payload + FD_SIZE.
     The bootloader-supplied x0 points at its own FDT which lacks
     linux,initrd-start, so force the DTB that ships in boot.img. */
  ldr   x2, =FD_SIZE
  add   x0, x1, x2
  mov   x4, x1
  ldr   x5, =FD_BASE
  cmp   x4, x5
  beq   _Entry
  ldr   x6,  =FD_SIZE

_CopyLoop:
  ldp   x2, x3, [x4], #16
  stp   x2, x3, [x5], #16
  subs  x6, x6, #16
  b.ne  _CopyLoop
  ldr   x5, =FD_BASE

_Entry:
  br    x5

_Dead:
  b     _Dead

.text
.align 4

_Payload:
'''


class BootImagePolicyTests(unittest.TestCase):
    def test_uncompressed_override_is_explicit(self):
        board = tomllib.loads((DEVICE / 'board.toml').read_text())
        self.assertEqual(board['bootimg']['image']['kernel_compression'], 'none')
        self.assertTrue(board['board']['example'])


@unittest.skipUnless(all(shutil.which(t) for t in ('git', 'clang', 'llvm-objcopy', 'llvm-nm', 'llvm-objdump')),
                     'requires git/LLVM cross-assembly tools')
class BootShimPatchTests(unittest.TestCase):
    def test_patch_compiles_header_and_preserves_x0_in_disassembly(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'BootShim').mkdir()
            source = root / 'BootShim/BootShim.S'
            source.write_text(BASELINE)
            patch = DEVICE / 'patches/uefi/0001-bootshim-preserve-runtime-fdt-and-size.patch'
            subprocess.run(['git', 'apply', '--check', str(patch)], cwd=root, check=True, capture_output=True)
            subprocess.run(['git', 'apply', str(patch)], cwd=root, check=True, capture_output=True)
            for header in (True, False):
                with self.subTest(requires_header=header):
                    scratch = root / ('header' if header else 'no-header')
                    scratch.mkdir()
                    shim = compile_shim(root, 0xa7100000, 0x300000, header, scratch)
                    if header:
                        self.assertEqual(shim[56:60], b'ARM\x64')
                        self.assertEqual(struct.unpack_from('<QQ', shim, 8), (0xa7100000, len(shim) + 0x300000))
                    result = subprocess.run(['llvm-objdump', '-d', str(scratch / 'shim.o')],
                                            check=True, capture_output=True, text=True)
                    # No x0 reference in executable instructions; literal pools/header
                    # data are marked data and not used for this handoff assertion.
                    instructions = [line for line in result.stdout.splitlines()
                                    if '\t' in line and not any(t in line for t in ('.word', '.xword', '.byte'))]
                    self.assertTrue(any('br\tx5' in line or 'br x5' in line for line in instructions), result.stdout)
                    self.assertFalse(any('x0' in line for line in instructions), result.stdout)


if __name__ == '__main__':
    unittest.main()
