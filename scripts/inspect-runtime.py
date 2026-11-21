#!/usr/bin/env python3
"""Validate a KernelSU read-only runtime capture without modifying a device."""
from __future__ import annotations
import argparse, json, re, struct, sys
from pathlib import Path

def hexfile(root,name):
    p=root/name
    if not p.is_file(): raise ValueError(f"missing capture: {p}")
    raw=bytes.fromhex(p.read_text().replace('\n',' '))
    return raw

def ranges_from_iomem(path):
    out=[]
    for line in path.read_text().splitlines():
        if line.startswith(' ') or 'System RAM' not in line: continue
        m=re.match(r'([0-9a-f]+)-([0-9a-f]+) : System RAM',line)
        if m:
            a,e=int(m.group(1),16),int(m.group(2),16)+1
            if e>a: out.append({'base':a,'end':e,'size':e-a})
    return out

def inspect(root):
    root=Path(root).expanduser().resolve(); errors=[]
    model=hexfile(root,'model.hex').rstrip(b'\0').decode('utf-8','replace')
    compat=hexfile(root,'compatible.hex').rstrip(b'\0').decode('utf-8','replace').split('\0')
    msm=list(struct.unpack('>'+('I'*(len(hexfile(root,'qcom,msm-id.hex'))//4)),hexfile(root,'qcom,msm-id.hex')))
    board=list(struct.unpack('>'+('I'*(len(hexfile(root,'qcom,board-id.hex'))//4)),hexfile(root,'qcom,board-id.hex')))
    start=int.from_bytes(hexfile(root,'initrd-start.hex'),'big'); end=int.from_bytes(hexfile(root,'initrd-end.hex'),'big')
    iomem=ranges_from_iomem(root/'proc-iomem'); containing=[r for r in iomem if r['base']<=start and end<=r['end']]
    reserved=[]
    for line in (root/'proc-iomem').read_text().splitlines():
        m=re.match(r'\s+([0-9a-f]+)-([0-9a-f]+) : reserved',line)
        if m: reserved.append((int(m.group(1),16),int(m.group(2),16)+1))
    reserved_hit=[{'base':a,'end':e} for a,e in reserved if a<end and start<e]
    memory=hexfile(root,'memory-reg.hex'); vals=list(struct.unpack('>'+('I'*(len(memory)//4)),memory)); tuples=[]
    if len(vals)%4: errors.append('memory/reg is not a multiple of four cells')
    for i in range(0,len(vals)-3,4): tuples.append({'base':(vals[i]<<32)|vals[i+1],'size':(vals[i+2]<<32)|vals[i+3]})
    if any(not x['size'] for x in tuples): errors.append('runtime memory/reg contains zero-size entries')
    if not containing: errors.append('initrd is not contained by a System RAM iomem range')
    if not reserved_hit: errors.append('initrd has no /proc/iomem reserved overlap')
    report={'schema_version':1,'source':str(root),'identity':{'model':model,'compatible':compat,'msm_id':msm,'board_id':board,'onyx': 'onyx' in model.lower()},'initrd':{'start':start,'end':end,'size':max(0,end-start),'contained_system_ram':containing,'iomem_reserved_overlap':reserved_hit},'memory_reg':tuples,'system_ram':iomem,'errors':errors,'runtime_source_verified':True,'hardware_tested':True,'safe_to_boot':False,'notice':'Runtime property capture only; not a complete FDT or EFI memory map. safe_to_boot remains false.'}
    return report

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--capture',required=True,type=Path);p.add_argument('--json',action='store_true');a=p.parse_args(argv)
    try:r=inspect(a.capture); code=0 if not r['errors'] else 1
    except (OSError,ValueError,struct.error) as e:r={'errors':[str(e)],'safe_to_boot':False};code=1
    print(json.dumps(r,ensure_ascii=False,indent=2,sort_keys=True) if a.json else ('OK' if code==0 else 'ERROR: '+ '; '.join(r['errors']))); return code
if __name__=='__main__':sys.exit(main())
