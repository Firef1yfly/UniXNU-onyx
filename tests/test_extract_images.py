"""Tests for bounded Android image evidence extraction."""
from pathlib import Path
import hashlib
import importlib.util
import json
import tempfile
import unittest
from zipfile import ZipFile, ZIP_DEFLATED
SPEC=importlib.util.spec_from_file_location('extract_images',Path(__file__).resolve().parents[1]/'scripts/extract-images.py'); TOOL=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(TOOL)

def make_dt(model=b'onx'):
    # Minimal valid FDT is easier generated with dtc in test fixture.
    import subprocess
    with tempfile.TemporaryDirectory() as t:
        d=Path(t); s=d/'a.dts'; o=d/'a.dtb'; s.write_text('/dts-v1/; / { model = "Qualcomm Technologies, Inc. Onyx based on SM8735"; compatible = "qcom,tuna"; };'); subprocess.run(['dtc','-I','dts','-O','dtb','-o',str(o),str(s)],check=True,capture_output=True); return o.read_bytes()

class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name); self.archive=self.root/'images.zip'; dt=make_dt()
        # vendor boot v4 with one DTB; DTBO table with one entry.
        page=4096; hs=2128; ram=b'RAMDISK'; voff=4096; dtb_off=voff+((len(ram)+page-1)//page*page); v=bytearray(dtb_off+len(dt)); v[:8]=b'VNDRBOOT'; import struct; struct.pack_into('<II',v,8,4,page); struct.pack_into('<I',v,24,len(ram)); struct.pack_into('<IIQ',v,2096,hs,len(dt),0x1f00000); v[voff:voff+len(ram)]=ram; v[dtb_off:dtb_off+len(dt)]=dt
        entry_off=32; blob_off=64; total=blob_off+len(dt); d=bytearray(total); struct.pack_into('>8I',d,0,TOOL.DTBO_MAGIC,total,32,32,1,entry_off,page,0); struct.pack_into('>8I',d,entry_off,len(dt),blob_off,0,0,0,0,0,0); d[blob_off:]=dt
        with ZipFile(self.archive,'w',ZIP_DEFLATED) as z:
            z.writestr('images/boot.img',b'ANDROID!'); z.writestr('images/vendor_boot.img',bytes(v)); z.writestr('images/dtbo.img',bytes(d))
    def tearDown(self): self.t.cleanup()
    def test_extract_manifest_and_no_overwrite(self):
        out=self.root/'out'; r=TOOL.extract(self.archive,out); self.assertEqual(len(r['trees']),2); self.assertTrue((out/'manifest.json').is_file()); self.assertEqual(r['archive']['sha256'],hashlib.sha256(self.archive.read_bytes()).hexdigest());
        with self.assertRaises(ValueError): TOOL.extract(self.archive,out)
    def test_reject_missing_member(self):
        bad=self.root/'bad.zip'
        with ZipFile(bad,'w') as z:z.writestr('images/boot.img',b'ANDROID!')
        with self.assertRaises(KeyError): TOOL.extract(bad,self.root/'badout')
if __name__=='__main__': unittest.main()
