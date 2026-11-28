#!/usr/bin/env python3
"""The onyx ABL adds text_offset to the jump address, so packing must clear it."""
import importlib.util
import struct
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEVICE = HERE.parent
SPEC = importlib.util.spec_from_file_location("menu_image", DEVICE / "scripts/make-menu-image.py")
SCRIPT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCRIPT)

PAGE = 4096


def fake_image(text_offset: int, header_size: int = 1584, kernel_size: int = 0x4000) -> bytes:
    header = bytearray(PAGE * max(1, -(-header_size // PAGE)) + kernel_size)
    header[0:8] = b"ANDROID!"
    struct.pack_into("<I", header, 8, kernel_size)
    struct.pack_into("<I", header, SCRIPT.HEADER_SIZE_OFFSET, header_size)
    struct.pack_into("<I", header, SCRIPT.HEADER_VERSION_OFFSET, 4)
    start = PAGE * max(1, -(-header_size // PAGE))
    struct.pack_into("<Q", header, start + SCRIPT.TEXT_OFFSET_POSITION, text_offset)
    struct.pack_into("<Q", header, start + 16, kernel_size)
    header[start + 56:start + 60] = b"ARM\x64"
    return bytes(header)


class TextOffsetTests(unittest.TestCase):
    def test_kernel_field_starts_after_the_padded_header(self):
        self.assertEqual(SCRIPT.kernel_field_offset(fake_image(0x1234)), PAGE)
        self.assertEqual(SCRIPT.kernel_field_offset(fake_image(0x1234, header_size=5000)), 2 * PAGE)

    def test_firmware_base_is_cleared_and_reported(self):
        image = fake_image(0xA7100000)
        fixed, previous = SCRIPT.zero_text_offset(image)
        self.assertEqual(previous, 0xA7100000)
        self.assertEqual(struct.unpack_from("<Q", fixed, PAGE + SCRIPT.TEXT_OFFSET_POSITION)[0], 0)

    def test_everything_except_that_field_is_untouched(self):
        image = fake_image(0xA7100000)
        fixed, _ = SCRIPT.zero_text_offset(image)
        self.assertEqual(len(fixed), len(image))
        field = range(PAGE + SCRIPT.TEXT_OFFSET_POSITION, PAGE + SCRIPT.TEXT_OFFSET_POSITION + 8)
        changed = [i for i in range(len(image)) if image[i] != fixed[i]]
        self.assertTrue(changed, "the field should change for a non-zero value")
        self.assertEqual([i for i in changed if i not in field], [],
                         "nothing outside the text_offset field may change")
        self.assertEqual(fixed[PAGE + 56:PAGE + 60], b"ARM\x64")

    def test_already_zero_is_left_alone(self):
        image = fake_image(0)
        fixed, previous = SCRIPT.zero_text_offset(image)
        self.assertEqual(previous, 0)
        self.assertEqual(fixed, image)

    def test_large_header_uses_the_next_page_boundary(self):
        image = fake_image(0xA7100000, header_size=5000)
        fixed, _ = SCRIPT.zero_text_offset(image)
        self.assertEqual(struct.unpack_from("<Q", fixed, 2 * PAGE + SCRIPT.TEXT_OFFSET_POSITION)[0], 0)


if __name__ == "__main__":
    unittest.main()
