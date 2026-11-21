"""Host binding tests, NOT onyx runtime/device validation.

Requires dtc and sibling ../unixnu. Any nonzero DRAM used below is a synthetic
encoding fixture in a temporary directory, never a board configuration.
"""
import importlib.util
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

DEVICE = Path(__file__).resolve().parents[1]
UPSTREAM = DEVICE.parent / 'unixnu'
sys.path.insert(0, str(UPSTREAM / 'scripts'))
from unixnu.devicetree import generate, read_fdt, registers, hardware_properties, arm_io_window
from unixnu.util import Error


@unittest.skipUnless(shutil.which('dtc'), 'requires dtc')
class Sm8735BindingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dtb = Path(self.temp.name) / 'hardware.dtb'
        self.compile(DEVICE / 'dts/onyx-bringup.dts')
        self.root = read_fdt(self.dtb.read_bytes())

    def compile(self, source):
        result = subprocess.run(['dtc', '-I', 'dts', '-O', 'dtb', '-i', str(DEVICE / 'soc/dts'),
                                 '-o', str(self.dtb), str(source)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '', 'minimal tree must compile without warnings')

    def child(self, name):
        return next(n for n in self.root.children if n.name == name)

    def test_cpu_affinities_and_single_candidate_policy(self):
        cpus = self.child('cpus')
        self.assertEqual(cpus.scalar('timebase-frequency'), 19200000)
        self.assertEqual([registers(c)[0][0] for c in cpus.children], list(range(0, 0x800, 0x100)))
        self.assertEqual([registers(c)[0][0] for c in cpus.children if c.enabled()], [0])
        self.assertTrue(all(c.strings('compatible') == ['qcom,kryo'] for c in cpus.children))
        self.assertFalse(any('unixnu,cluster-type' in c.properties for c in cpus.children))

    def test_gic_adt_name_stride_and_translated_registers(self):
        gic = next(n for n in self.root.walk() if n.strings('unixnu,adt-name') == ['intc'])
        self.assertEqual(gic.strings('compatible'), ['arm,gic-v3'])
        self.assertEqual(registers(gic), [(0x17100000, 0x10000), (0x17180000, 0x200000)])
        base, size = arm_io_window([gic])
        props = dict(hardware_properties(gic, {gic.scalar('phandle'): gic}, base))
        self.assertGreater(base, 0)
        pairs = struct.unpack('<QQQQ', props['reg'])
        self.assertEqual((base + pairs[0], pairs[1], base + pairs[2], pairs[3]),
                         (0x17100000, 0x10000, 0x17180000, 0x200000))
        self.assertEqual(struct.unpack('<Q', props['redistributor-stride']), (0x40000,))

    def test_timer_psci_and_board_selection(self):
        self.assertEqual(self.child('psci').strings('method'), ['smc'])
        timer = self.child('timer')
        self.assertEqual(timer.scalar('clock-frequency'), 19200000)
        self.assertEqual(timer.cells('interrupts'), [1, 13, 0xff08, 1, 14, 0xff08, 1, 11, 0xff08, 1, 12, 0xff08])
        self.assertEqual(self.root.cells('qcom,msm-id'), [681, 0x10000, 655, 0x10000])
        self.assertEqual(self.root.cells('xiaomi,miboard-id'), [7, 0])

    def test_unresolved_dram_is_rejected_by_real_generator(self):
        self.assertEqual(registers(self.child('memory@0')), [(0, 0)])
        with self.assertRaisesRegex(Error, 'nonempty DRAM'):
            generate(self.dtb, {})

    def test_synthetic_memory_allows_binding_encoding_only(self):
        # THIS RANGE IS NOT AN ONYX MEASUREMENT. Never write it to board DTS.
        source = (DEVICE / 'dts/onyx-bringup.dts').read_text()
        fixture = Path(self.temp.name) / 'synthetic.dts'
        fixture.write_text(source.replace('memory@0 {', 'memory@80000000 {').replace('reg = <0 0 0 0>;', 'reg = <0 0x80000000 0 0x40000000>;'))
        self.compile(fixture)
        adt = generate(self.dtb, {})
        self.assertIn(b'intc\0', adt)
        self.assertIn(b'cpu0\0', adt)
        self.assertNotIn(b'cpu1\0', adt)
        self.assertIn(b'arm,gic-v3\0', adt)


if __name__ == '__main__':
    unittest.main()
