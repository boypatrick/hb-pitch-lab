#!/usr/bin/env python3
"""Yosys structural/generic synthesis checks, with RTL/model resource cross-checks."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parent

def inventory(netlist,top):
    modules=netlist['modules'];counts=Counter();memory_bits=0
    def walk(name):
        nonlocal memory_bits
        m=modules[name]
        for memory in m.get('memories',{}).values():memory_bits+=memory['width']*memory['size']
        for cell in m.get('cells',{}).values():
            kind=cell['type']
            if kind in modules:walk(kind)
            else:counts[kind]+=1
    walk(top)
    return counts,memory_bits

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();generated=args.generated.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    binary=os.environ.get('YOSYS') or shutil.which('yosys') or str(ROOT/'.tooldeps/yosys/0.68/bin/yosys')
    version=subprocess.check_output([binary,'-V'],text=True).strip()
    manifest=json.loads((generated/'manifest.json').read_text())
    files=(generated/'files.f').read_text().splitlines()
    # Copy source paths into a validation script. No writes to the frozen candidate.
    read='read_verilog -sv '+' '.join('"'+str(generated/f)+'"' for f in files)+'\n'
    def check(name,commands):
        path=out/(name+'.ys');path.write_text(read+commands+f'\nwrite_json {name}.json\n')
        with (out/(name+'.log')).open('w') as log:
            result=subprocess.run([binary,'-Q','-T','-s',str(path)],cwd=out,stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:raise RuntimeError(f'Synthesis failed: {out}/{name}.log')
        return json.loads((out/(name+'.json')).read_text())
    tops=('lab_system_top','lab_tile_top','lab_tier0_top','lab_tier1_top')
    for top in tops:
        net=check(top,f'hierarchy -check -top {top}\nproc\nopt\ncheck -assert\nstat')
        if top=='lab_system_top':before,mem=inventory(net,top)
    generic=check('generic_system','synth -top lab_system_top -noabc\ncheck -assert\nstat')
    after,_=inventory(generic,'lab_system_top')
    expected_macs=manifest['resolved_design']['tile_count']*sum(m['resources']['macs_per_cycle'] for m in manifest['modules'])
    expected_memory=manifest['resolved_design']['tile_count']*sum(m['resources']['memory_bits'] for m in manifest['modules'])
    if before['$mul']!=expected_macs or mem!=expected_memory:
        raise RuntimeError('Synthesized hierarchy differs from evaluated MAC/memory resource counts')
    if any('LATCH' in kind.upper() for kind in after):raise RuntimeError('Unexpected latch inferred')
    report={'tool':version,'point_id':manifest['point_id'],'structural_tops':list(tops),
            'model_macs':expected_macs,'yosys_multipliers':before['$mul'],
            'model_memory_bits':expected_memory,'yosys_memory_bits':mem,
            'generic_leaf_cells':sum(after.values()),'generic_cell_types':dict(after),
            'scope':'Generic bit-level synthesis without ABC/Liberty/SRAM macro mapping; no physical area, timing, power or SoIC signoff.'}
    (out/'synthesis_validation.json').write_text(json.dumps(report,indent=2))
    print(f'Four structural tops and generic system synthesis passed; {expected_macs} multipliers and {expected_memory} memory bits match the model.')

if __name__=='__main__':main()
