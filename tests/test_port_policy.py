import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DevicePortPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board = tomllib.loads((ROOT / "board.toml").read_text(encoding="utf-8"))
        cls.dts = (ROOT / "dts/onyx-bringup.dts").read_text(encoding="utf-8")

    def test_incomplete_port_keeps_example_gate_and_memory_placeholder(self):
        self.assertIs(self.board["board"]["example"], True)
        self.assertIn("reg = <0 0 0 0>;", self.dts)

    def test_menu_payload_enables_tools_without_guessing_private_inputs(self):
        self.assertIs(self.board["payload"].get("tools"), True)
        self.assertEqual(self.board["package"]["unixnu"], "../UniXNU")
        self.assertEqual(self.board["payload"]["adt"]["unique_chip_id"], "required")
        bootimg = self.board.get("bootimg", {})
        self.assertNotIn("dtb", bootimg)
        self.assertNotIn("firmware_dtb", bootimg)


if __name__ == "__main__":
    unittest.main()
