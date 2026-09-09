"""Frozen parameter export and independent RTL cycle replay for MTIA subsystem."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from module_specs import ROOT, digest
from optimize import write_json
from mtia_model import PARTITIONS, io_contract, candidates, validate_design

RTL_FILES = ('mtia_transport','mtia_scratch','mtia_pe','mtia_me_nmc','mtia_cluster')


def parameters(d,c):
    p=d['parameters']
    return {'PES':p['pes'],'LANES':p['lanes'],'ROWS':p['scratch_rows'],'ENTRIES':p['shared_entries'],
            'CUT':PARTITIONS[c['partition']],'HB_BITS':c['hb_bits'],
            'COARSE_BITS':d['physical']['coarse_bits'],'STAGES':d['physical']['link_stages']}


def export(d,c,point_id,out,engine_sha):
    validate_design(d)
    if c not in list(candidates(d)) or not c['geometric_feasible']:
        raise ValueError('Only a registered, geometrically feasible candidate may be exported')
    out=Path(out)
    if out.exists():raise ValueError('RTL directory exists; never overwrite frozen exports')
    (out/'rtl').mkdir(parents=True)
    for name in RTL_FILES:shutil.copyfile(ROOT/'rtl'/f'{name}.sv',out/'rtl'/f'{name}.sv')
    params=parameters(d,c);inputs,outputs=io_contract(d['parameters'])
    ports=['input wire clk','input wire rst']
    ports += [f"{'input' if fields is inputs else 'output'} wire "+(f'[{w-1}:0] ' if w>1 else '')+k
              for fields in (inputs,outputs) for k,w in fields]
    wrapper='module mtia_selected_top(\n    '+',\n    '.join(ports)+'\n);\n'
    wrapper+='    mtia_cluster #(\n        '+', '.join(f'.{k}({v})' for k,v in params.items())+'\n    ) cluster (.*);\nendmodule\n'
    (out/'rtl/mtia_selected_top.sv').write_text(wrapper)
    files=['rtl/'+name+'.sv' for name in RTL_FILES]+['rtl/mtia_selected_top.sv']
    (out/'files.f').write_text('\n'.join(files)+'\n')
    (out/'clock.sdc').write_text(f'create_clock -name clk -period {1e9/d["clock_hz"]:.9g} [get_ports clk]\n')
    cut=c['partition'];mapping={}
    for j in range(params['PES']):
        base=f'cluster.pe_tile[{j}]'
        mapping[base+'.pe']=0;mapping[base+'.scratch']=1 if cut=='local_scratch' else 0
        for link in ('request_link','response_link','result_link'):
            mapping[base+'.'+link]='boundary' if (cut=='local_scratch' or link=='result_link' and cut=='coarse') else 0
    mapping['cluster.collective']=0 if cut=='2d' else 1
    mapping['cluster.dma_link']='boundary' if cut=='coarse' else mapping['cluster.collective']
    manifest={'format':'mtia-rtl-v1','point_id':point_id,'engine_sha256':engine_sha,'candidate':c,
              'parameters':params,'files':files,'file_sha256':{f:hashlib.sha256((out/f).read_bytes()).hexdigest() for f in files},
              'input_ports':dict(inputs),'output_ports':dict(outputs),'placement_intent':mapping,
              'precision':'signed INT8 operands, wrapping INT32 reduction',
              'scope':'Connected research subsystem; placement intent only, not split-die netlists or timing closure.'}
    write_json(out/'manifest.json',manifest)
    return manifest


def run(command,cwd,log,timeout=180):
    with Path(log).open('w') as f:
        f.write('argv: '+json.dumps([str(x) for x in command])+'\n');f.flush()
        result=subprocess.run([str(x) for x in command],cwd=cwd,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
    if result.returncode:raise RuntimeError('RTL/EDA command failed: '+str(log))


def compiler():
    local=ROOT/'.tooldeps/icarus-verilog/13.0'
    iv=os.environ.get('IVERILOG') or shutil.which('iverilog')
    return [iv] if iv else [local/'bin/iverilog','-B',local/'lib/ivl']


def compile_rtl(d,c,out,generated=None):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    files=[ROOT/'rtl'/f'{name}.sv' for name in RTL_FILES] if generated is None else [Path(generated)/'rtl'/f'{name}.sv' for name in RTL_FILES]
    defines=[]
    if generated is not None:
        files.append(Path(generated)/'rtl/mtia_selected_top.sv')
        defines=['-DMTIA_FROZEN_TOP']
    image=out/'simulation.vvp'
    run(compiler()+['-g2012','-Wall','-s','tb_mtia','-o',image]+defines+[f'-Ptb_mtia.{k}={v}' for k,v in parameters(d,c).items()]+
        [f'-Ptb_mtia.MAX_CYCLES={d["max_cycles"]}']+files+[ROOT/'tests/tb_mtia.sv'],ROOT,out/'compile.log')
    return image


def replay_stimulus(image,stimulus,out):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    for j,name in enumerate(('stimulus','expected','mask')):
        (out/(name+'.hex')).write_text(''.join(f'{row[j]:x}\n' for row in stimulus))
    vvp=os.environ.get('VVP') or shutil.which('vvp') or ROOT/'.tooldeps/icarus-verilog/13.0/bin/vvp'
    log=out/'simulation.log'
    run([vvp,image,f'+STIM={out}/stimulus.hex',f'+EXPECT={out}/expected.hex',f'+MASK={out}/mask.hex',f'+CYCLES={len(stimulus)}'],ROOT,log)
    if f'PASS mtia cycles={len(stimulus)} ' not in log.read_text():raise RuntimeError('No complete RTL replay marker')
    return {'status':'PASS','cycles':len(stimulus),'stimulus_sha256':digest(stimulus)}


def synthesis(generated,out):
    from check_synthesis import inventory
    from optimize import read_json
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True);generated=Path(generated).resolve()
    m=read_json(generated/'manifest.json');p=m['parameters']
    binary=os.environ.get('YOSYS') or shutil.which('yosys') or str(ROOT/'.tooldeps/yosys/0.68/bin/yosys')
    source='read_verilog -sv '+' '.join('"'+str(generated/f)+'"' for f in m['files'])+'\n'
    # Keep memory as logical banks. Generic mapping is NOT a SRAM macro cost.
    script=source+'hierarchy -check -top mtia_selected_top\nproc\nopt\ncheck -assert\nwrite_json structure.json\n'
    script+='synth -top mtia_selected_top -run begin:coarse\ntechmap\nopt\ncheck -assert\nwrite_json generic.json\nstat\n'
    (out/'check.ys').write_text(script);run([binary,'-Q','-T','-s',out/'check.ys'],out,out/'synthesis.log',300)
    net=read_json(out/'structure.json');counts,memory=inventory(net,'mtia_selected_top')
    expected=p['PES']*p['LANES']*8*p['ROWS']+p['ENTRIES']*32
    if counts['$mul']!=p['PES']*p['LANES'] or memory!=expected:
        raise RuntimeError(f'MTIA resource mismatch: multipliers={counts["$mul"]}, memory={memory}, expected={expected}')
    after,_=inventory(read_json(out/'generic.json'),'mtia_selected_top')
    if any('LATCH' in k.upper() for k in after):raise RuntimeError('Unexpected latch')
    result={'status':'PASS','point_id':m['point_id'],'tool':subprocess.check_output([binary,'-V'],text=True).strip(),
            'multipliers':counts['$mul'],'memory_bits':memory,'generic_cells':sum(after.values()),
            'scope':'Generic synthesis with memories retained; no Liberty mapping, SRAM macro binding or physical timing.'}
    write_json(out/'synthesis.json',result);return result
