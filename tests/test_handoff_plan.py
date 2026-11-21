"""Compile and execute real C planning code on synthetic addresses, never a phone."""
import ctypes as C
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
class Span(C.Structure):
    _fields_ = [('base', C.c_uint64), ('size', C.c_uint64)]
class Plan(C.Structure):
    _fields_ = [('fdt_pages', Span), ('initrd_pages', Span), ('fdt_bytes', C.c_uint32)]


def header(**kw):
    fields = dict(magic=0xd00dfeed, total=128, structure=56, strings=96, reserve=40,
                  version=17, compatible=16, bootcpu=0, str_size=32, struct_size=40)
    fields.update(kw)
    return struct.pack('>10I', *fields.values())


@unittest.skipUnless(shutil.which('clang'), 'requires clang')
class HandoffPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        out = Path(cls.temp.name) / 'plan.so'
        src = ROOT / 'package/HandoffPlan/HandoffPlan.c'
        subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fPIC','-shared',str(src),'-o',str(out)], check=True)
        cls.lib = C.CDLL(str(out))
        cls.fn = cls.lib.OnyxPlanHandoff
        cls.fn.argtypes = [C.POINTER(C.c_uint8),C.c_size_t,C.c_uint64,C.c_uint64,C.c_uint64,C.c_uint64,
                           C.POINTER(Span),C.c_size_t,C.POINTER(Span),C.c_size_t,C.POINTER(Plan)]
        cls.fn.restype = C.c_int

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_plan(self, h=None, address=0x81000000, readable=128, start=0x82000000, end=0x82002000,
                 ram=((0x80000000,0x10000000),), forbidden=()):
        raw = header() if h is None else h
        buf=(C.c_uint8*len(raw)).from_buffer_copy(raw)
        banks=(Span*len(ram))(*(Span(*s) for s in ram))
        blocked=(Span*len(forbidden))(*(Span(*s) for s in forbidden))
        out=Plan(Span(0x1111,0x2222),Span(0x3333,0x4444),0x5555)
        before=bytes(out)
        rc=self.fn(buf,len(raw),address,readable,start,end,banks,len(ram),blocked,len(forbidden),C.byref(out))
        if rc:self.assertEqual(bytes(out),before,'Failure must not publish a partial plan')
        return rc,out

    def test_valid_ranges_are_page_reserved(self):
        rc,out=self.run_plan(address=0x81000008,start=0x82000003,end=0x82002001)
        self.assertEqual(rc,0)
        self.assertEqual((out.fdt_pages.base,out.fdt_pages.size),(0x81000000,0x1000))
        self.assertEqual((out.initrd_pages.base,out.initrd_pages.size),(0x82000000,0x3000))
        self.assertEqual(out.fdt_bytes,128)

    def test_invalid_header_or_blocks_rejected(self):
        for kw in ({'magic':0}, {'total':39}, {'total':0x1000001}, {'version':16}, {'compatible':18},
                   {'structure':57}, {'str_size':100}, {'reserve':48}, {'strings':72}, {'struct_size':0}):
            with self.subTest(kw=kw):self.assertEqual(self.run_plan(h=header(**kw))[0],2)

    def test_short_header_copy_rejected(self):
        self.assertEqual(self.run_plan(h=header()[:39])[0],1)

    def test_no_dereference_of_supplied_physical_address(self):
        # These numeric addresses cannot be dereferenced in this host process.
        self.assertEqual(self.run_plan()[0],0)

    def test_readable_extent_and_alignment_rejected(self):
        for kw in ({'readable':127},{'address':0},{'address':0x81000004}):
            with self.subTest(kw=kw):self.assertEqual(self.run_plan(**kw)[0],3)

    def test_invalid_initrd_and_overflow_rejected(self):
        for kw in ({'start':0},{'end':0x82000000},{'end':1},
                   {'address':0xfffffffffffffff8}, {'start':0xffffffffffffff00,'end':0xffffffffffffffff}):
            with self.subTest(kw=kw):self.assertEqual(self.run_plan(**kw)[0],3)

    def test_forbidden_raw_or_page_collisions_rejected(self):
        for span in ((0x81000080,1),(0x82001000,1),(0x81000000,0x8000000)):
            with self.subTest(span=span):self.assertEqual(self.run_plan(forbidden=(span,))[0],5)

    def test_fdt_initrd_rounded_page_collision_rejected(self):
        self.assertEqual(self.run_plan(start=0x81000080,end=0x81000100)[0],5)

    def test_unknown_ram_and_noncoalesced_bank_boundary_rejected(self):
        self.assertEqual(self.run_plan(ram=((0x80000000,0x1000000),))[0],4)
        self.assertEqual(self.run_plan(start=0x82000000,end=0x82002000,
            ram=((0x81000000,0x1000),(0x82000000,0x1000),(0x82001000,0x1000)))[0],4)

    def test_invalid_caller_maps_rejected(self):
        for kw in ({'ram':()}, {'ram':((0x80000001,0x1000),)}, {'ram':((0x80000000,0x1001),)},
                   {'ram':((0x80000000,0),)}, {'ram':((0x80000000,0x1000),(0x80000000,0x2000))},
                   {'forbidden':((0xfffffffffffffff0,0x20),)}, {'forbidden':((0x80000000,0),)}):
            with self.subTest(kw=kw):self.assertEqual(self.run_plan(**kw)[0],1)

    def test_touching_forbidden_boundary_is_allowed(self):
        self.assertEqual(self.run_plan(forbidden=((0x81001000,0x1000),(0x81fff000,0x1000)))[0],0)

    def test_real_source_cross_compiles_freestanding_aarch64(self):
        subprocess.run(['clang','--target=aarch64-none-elf','-ffreestanding','-std=c11',
                        '-Wall','-Wextra','-Werror','-c',str(ROOT/'package/HandoffPlan/HandoffPlan.c'),
                        '-o',str(Path(self.temp.name)/'plan-aarch64.o')],check=True)


if __name__=='__main__':unittest.main()
