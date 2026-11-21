"""Offline tests: synthetic fixtures are NOT real onyx hardware evidence."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('check_inputs', Path(__file__).resolve().parents[1] / 'scripts/check-inputs.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class CheckInputsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.device, self.upstream, self.soc = (self.root / p for p in ('device', 'unixnu', 'soc'))
        self.board = '''[board]
example = false
name = "fixture"
soc = "SM8735"
soc_source = "sm8735"
os_profile = "ipados-test"
[kernel]
defconfig = "fixture_defconfig"
config_fragments = ["soc:configs/sm8735.config", "os:configs/ipados.config"]
[device_tree]
source = "device:dts/fixture.dts"
[payload.adt]
unique_chip_id = "required"
'''
        self.put(self.device / 'board.toml', self.board)
        self.put(self.device / 'porting.toml', '[device]\nname="fixture"\nsoc="SM8735"\nos_profile="ipados-test"\n')
        self.put(self.device / 'feeds.toml', '[[source]]\nname="sm8735"\nkind="soc"\nlocal="../soc"\n')
        self.put(self.device / 'configs/fixture_defconfig', '# synthetic\n')
        self.put(self.device / 'dts/fixture.dts', '/dts-v1/; / { memory { device_type = "memory"; reg = <0 0x80000000 0 0x40000000>; }; };')
        self.put(self.device / 'inputs.toml', '[device]\nname="fixture"\nfirmware_version="synthetic-test-only"\n[memory]\nsource="synthetic fixture, not hardware"\nsha256="' + 'ab' * 32 + '"\n')
        self.put(self.upstream / 'profiles/os/ipados-test/profile.toml', '[os]\n')
        self.put(self.upstream / 'profiles/os/ipados-test/configs/ipados.config', '# fixture\n')
        self.put(self.soc / 'soc.toml', '[soc]\n')
        self.put(self.soc / 'configs/sm8735.config', '# fixture\n')
        (self.soc / 'dts').mkdir()

    @staticmethod
    def put(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def result(self):
        return CHECK.audit(self.device, self.upstream)

    def status(self, identifier):
        return next(c['status'] for c in self.result()['checks'] if c['id'] == identifier)

    def test_complete_fixture_not_hardware_verified(self):
        self.assertTrue(self.result()['complete'])
        self.assertFalse(self.result()['hardware_tested'])
        self.assertIn('no build', self.result()['notice'])

    def test_example_is_blocked(self):
        self.put(self.device / 'board.toml', self.board.replace('example = false', 'example = true'))
        self.assertEqual(self.status('board.example'), 'error')

    def test_missing_profile(self):
        self.put(self.device / 'board.toml', self.board.replace('ipados-test', 'ios-missing'))
        self.assertEqual(self.status('os.profile'), 'error')

    def test_missing_defconfig(self):
        self.put(self.device / 'board.toml', self.board.replace('fixture_defconfig', 'missing_defconfig'))
        self.assertEqual(self.status('defconfig:missing_defconfig'), 'error')

    def test_record_identity(self):
        self.put(self.device / 'porting.toml', '[device]\nname="example"\n')
        self.assertEqual(self.status('record.name'), 'error')
        self.assertEqual(self.status('record.soc'), 'error')

    def test_file_feed_and_missing_soc_manifest(self):
        self.put(self.device / 'feeds.toml', '[[source]]\nname="sm8735"\nkind="soc"\ngit="' + self.soc.as_uri() + '"\n')
        self.assertTrue(self.result()['complete'])
        # Point at an existing but incomplete directory without deleting files.
        self.put(self.device / 'feeds.toml', '[[source]]\nname="sm8735"\nkind="soc"\nlocal="../device"\n')
        self.assertEqual(self.status('soc.manifest'), 'error')

    def test_remote_feed_pending_without_network(self):
        self.put(self.device / 'feeds.toml', '[[source]]\nname="sm8735"\nkind="soc"\ngit="https://invalid.example/no-fetch"\n')
        self.assertEqual(self.status('soc.source'), 'pending')
        self.assertFalse(self.result()['complete'])

    def test_fixed_identity_seed(self):
        self.put(self.device / 'board.toml', self.board.replace('"required"', '"0x1234567890abcdef"'))
        self.assertEqual(self.status('identity.seed'), 'error')

    def test_zero_memory(self):
        self.put(self.device / 'dts/fixture.dts', '/ { memory { reg = <0 0 0 0>; }; };')
        self.assertEqual(self.status('dts.memory'), 'error')

    def test_uninterpretable_memory_pending(self):
        self.put(self.device / 'dts/fixture.dts', '#include "memory.dtsi"\n/ { };')
        self.assertEqual(self.status('dts.memory'), 'pending')
        self.assertFalse(self.result()['complete'])

    def test_include_with_literal_still_pending(self):
        self.put(self.device / 'dts/fixture.dts', '#include "other.dtsi"\n/ { memory { reg = <0 0x80000000 0 0x40000000>; }; };')
        self.assertEqual(self.status('dts.memory'), 'pending')

    def test_missing_provenance(self):
        self.put(self.device / 'inputs.toml', '# no actual evidence\n')
        self.assertEqual(self.status('board.provenance'), 'error')

    def test_json_cli_success_and_failure(self):
        for valid in (True, False):
            if not valid:
                self.put(self.device / 'board.toml', '[board')
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = CHECK.main(['--device', str(self.device), '--unixnu', str(self.upstream), '--json'])
            report = json.loads(stdout.getvalue())
            self.assertEqual(code, 0 if valid else 1)
            self.assertEqual(report['complete'], valid)


if __name__ == '__main__':
    unittest.main()
