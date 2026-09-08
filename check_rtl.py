#!/usr/bin/env python3
"""Run RTL scoreboards and elaborate all frozen candidate top-level views."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parent

def run(command,cwd,log):
    result=subprocess.run([str(s) for s in command],cwd=cwd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    log.write_text(result.stdout)
    if result.returncode:
        raise RuntimeError(f'RTL check failed: {log}\n{result.stdout}')
    return result.stdout

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    local=ROOT/'.tooldeps/icarus-verilog/13.0'
    iv=os.environ.get('IVERILOG') or shutil.which('iverilog')
    vvp=os.environ.get('VVP') or shutil.which('vvp')
    compiler=[iv] if iv else [local/'bin/iverilog','-B',local/'lib/ivl']
    simulator=vvp or local/'bin/vvp'
    version=run(compiler+['-V'],ROOT,out/'iverilog_version.log').splitlines()[0]
    cases=[('tb_stream',{'KIND':kind,'DEPTH':depth,'WIDTH':width}) for kind in (0,1) for depth,width in ((1,1),(3,8),(4,65),(2,128))]
    cases += [('tb_mac',{}),('tb_mac',{'ROWS':4,'COLS':4,'DATA_W':8,'ACC_W':32}),('tb_mac',{'ROWS':8,'COLS':4,'DATA_W':8,'ACC_W':32})]
    cases += [('tb_storage',{'DEPTH':d}) for d in (1,3,4)]
    cases += [('tb_arbiter',{'PORTS':p}) for p in (1,3,4)]
    reports=[]
    for index,(top,params) in enumerate(cases):
        name=f'{index:02d}_{top}';image=out/(name+'.vvp')
        command=compiler+['-g2012','-Wall','-s',top,'-o',image]
        command += [f'-P{top}.{key}={value}' for key,value in params.items()]
        command += list(sorted((ROOT/'rtl').glob('*.sv')))+[ROOT/'tests'/f'{top}.sv']
        run(command,ROOT,out/(name+'_compile.log'))
        output=run([simulator,image],ROOT,out/(name+'_run.log'))
        if 'PASS ' not in output:raise RuntimeError('Test did not report completion')
        reports.append({'test':top,'parameters':params,'result':output.strip()})
    generated=args.generated.resolve()
    files=(generated/'files.f').read_text().splitlines()
    for top in ('lab_system_top','lab_tile_top','lab_tier0_top','lab_tier1_top'):
        run(compiler+['-g2012','-Wall','-s',top,'-t','null']+files,generated,out/(top+'_elaborate.log'))
    report={'tool':version,'scoreboards':reports,'elaborated_tops':4,
            'candidate_point':json.loads((generated/'manifest.json').read_text())['point_id'],
            'scope':'Directed and deterministic randomized simulation; not exhaustive formal proof or physical timing closure.'}
    (out/'validation.json').write_text(json.dumps(report,indent=2))
    print(f'{len(reports)} RTL simulation cases passed; four generated tops elaborated. {out}/validation.json')

if __name__=='__main__':main()
