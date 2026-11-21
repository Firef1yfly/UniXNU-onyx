import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "parse-uefi-memory-report.py"
SPEC = importlib.util.spec_from_file_location("parse_uefi_memory_report", SCRIPT)
parser = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(parser)


def descriptor(typ, base, pages, attr=0x8):
    return {
        "type": typ,
        "physical_start": f"0x{base:x}",
        "virtual_start": "0x0",
        "number_of_pages": f"0x{pages:x}",
        "attribute": f"0x{attr:x}",
    }


def report():
    descriptors = [
        descriptor(0, 0x80000000, 0x100),
        descriptor(7, 0x80000000 + 0x100 * 0x1000, 0x200, 0x8 | 0x8000000000000000),
    ]
    return {
        "schema": "onyx-uefi-memory-report",
        "schema_version": 1,
        "device": "onyx",
        "capture": {
            "kind": "uefi_get_memory_map",
            "stage": "pre_exit_boot_services",
            "exit_boot_services": False,
        },
        "memory_map": {
            "descriptor_version": 1,
            "descriptor_size": 40,
            "descriptor_count": len(descriptors),
            "map_bytes": len(descriptors) * 40,
            "descriptors": descriptors,
        },
        "ram_partitions": {
            "protocol_revision": "0x10002",
            "count": 2,
            "entries": [
                {"base": "0x80000000", "available_length": "0x100000"},
                {"base": "0x90000000", "available_length": "0x200000"},
            ],
        },
        "associations": {
            "fdt": {
                "sha256": "a" * 64,
                "bytes": 847177,
                "source": "uefi_runtime_fdt",
            },
            "initrd": {
                "start": "0xb5921000",
                "end": "0xb7ffeb04",
                "source": "uefi_runtime_fdt_chosen",
            },
            "fd": {
                "base": "0xa7100000",
                "size": "0x300000",
                "sha256": "b" * 64,
                "source": "mu_uefi_fd",
            },
        },
    }


class UefiMemoryReport(unittest.TestCase):
    def test_valid_report_normalizes_ranges(self):
        result = parser.parse_report(report())
        self.assertEqual(result["memory_map"]["descriptor_count"], 2)
        self.assertEqual(result["memory_map"]["descriptor_size"], 40)
        self.assertEqual(result["memory_map"]["descriptors"][1]["end"], "0x80300000")
        self.assertEqual(result["ram_partitions"]["entries"][1]["end"], "0x90200000")
        self.assertEqual(result["associations"]["fd"]["base"], "0xa7100000")

    def test_rejects_android_or_luming_provenance(self):
        for marker in ("/proc/iomem", "Android", "luming"):
            value = copy.deepcopy(report())
            value["capture"]["stage"] = marker
            with self.subTest(marker=marker), self.assertRaisesRegex(parser.ReportError, "forbidden non-UEFI provenance"):
                parser.parse_report(value)

    def test_rejects_wrong_capture_kind_or_board(self):
        value = copy.deepcopy(report())
        value["capture"]["kind"] = "android_proc_iomem"
        with self.assertRaisesRegex(parser.ReportError, "forbidden non-UEFI provenance"):
            parser.parse_report(value)
        value = copy.deepcopy(report())
        value["device"] = "luming"
        with self.assertRaisesRegex(parser.ReportError, "forbidden non-UEFI provenance"):
            parser.parse_report(value)

    def test_descriptor_metadata_and_count_are_strict(self):
        for field, bad in (("descriptor_version", 2), ("descriptor_size", 32),
                           ("descriptor_size", 44), ("map_bytes", 41), ("descriptor_count", 1)):
            value = copy.deepcopy(report())
            value["memory_map"][field] = bad
            with self.subTest(field=field), self.assertRaises(parser.ReportError):
                parser.parse_report(value)

    def test_memory_type_range_ends_before_max(self):
        value = copy.deepcopy(report())
        value["memory_map"]["descriptors"][0]["type"] = 13
        parser.parse_report(value)
        value["memory_map"]["descriptors"][0]["type"] = 14
        with self.assertRaisesRegex(parser.ReportError, "not a UEFI memory type"):
            parser.parse_report(value)

        value = copy.deepcopy(report())
        value["memory_map"]["descriptors"][0]["attribute"] = "0x4000f00000000008"
        parser.parse_report(value)

        value = copy.deepcopy(report())
        value["memory_map"]["descriptors"][1]["physical_start"] = "0x80080000"
        with self.assertRaisesRegex(parser.ReportError, "overlap"):
            parser.parse_report(value)
        value = copy.deepcopy(report())
        value["memory_map"]["descriptors"] = [value["memory_map"]["descriptors"][0]]
        value["memory_map"]["descriptor_count"] = 1
        value["memory_map"]["map_bytes"] = 40
        value["memory_map"]["descriptors"][0]["number_of_pages"] = "0x1000000000000000"
        with self.assertRaisesRegex(parser.ReportError, "overflows"):
            parser.parse_report(value)
        value = copy.deepcopy(report())
        value["memory_map"]["descriptors"][0]["attribute"] = "0x20"
        with self.assertRaisesRegex(parser.ReportError, "unknown bits"):
            parser.parse_report(value)

    def test_rejects_partition_overlap_and_bad_range(self):
        value = copy.deepcopy(report())
        value["ram_partitions"]["entries"][1]["base"] = "0x80080000"
        with self.assertRaisesRegex(parser.ReportError, "overlap"):
            parser.parse_report(value)
        value = copy.deepcopy(report())
        value["ram_partitions"]["entries"][0]["available_length"] = "0x0"
        with self.assertRaises(parser.ReportError):
            parser.parse_report(value)

    def test_rejects_empty_partitions_and_wrong_protocol_revision(self):
        value = copy.deepcopy(report())
        value["ram_partitions"]["count"] = 0
        value["ram_partitions"]["entries"] = []
        with self.assertRaisesRegex(parser.ReportError, "between 1 and 4096"):
            parser.parse_report(value)
        value = copy.deepcopy(report())
        value["ram_partitions"]["protocol_revision"] = "0x10001"
        with self.assertRaisesRegex(parser.ReportError, "must be 0x10002"):
            parser.parse_report(value)

    def test_rejects_virtual_range_overflow(self):
        value = copy.deepcopy(report())
        value["memory_map"]["descriptors"][0]["virtual_start"] = "0xfffffffffffff000"
        value["memory_map"]["descriptors"][0]["number_of_pages"] = "0x2"
        with self.assertRaisesRegex(parser.ReportError, "physical or virtual range overflows"):
            parser.parse_report(value)

    def test_isa_attribute_requires_valid_bit(self):
        value = copy.deepcopy(report())
        value["memory_map"]["descriptors"][0]["attribute"] = "0x0000100000000008"
        with self.assertRaisesRegex(parser.ReportError, "ISA bits without"):
            parser.parse_report(value)
        value["memory_map"]["descriptors"][0]["attribute"] = "0x4000100000000008"
        parser.parse_report(value)

    def test_rejects_association_source_and_hash_errors(self):
        value = copy.deepcopy(report())
        value["associations"]["fdt"]["source"] = "android_runtime_fdt"
        with self.assertRaises(parser.ReportError):
            parser.parse_report(value)
        value = copy.deepcopy(report())
        value["associations"]["fd"]["sha256"] = "not-a-hash"
        with self.assertRaises(parser.ReportError):
            parser.parse_report(value)
        value = copy.deepcopy(report())
        value["associations"]["initrd"]["end"] = value["associations"]["initrd"]["start"]
        with self.assertRaises(parser.ReportError):
            parser.parse_report(value)

    def test_cli_reads_and_writes_normalized_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "input.json"
            output = Path(tmp) / "output.json"
            source.write_text(json.dumps(report()), encoding="utf-8")
            self.assertEqual(parser.main([str(source), "--output", str(output)]), 0)
            self.assertEqual(parser.load(output)["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
