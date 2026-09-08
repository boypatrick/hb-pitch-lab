#!/usr/bin/env python3
"""Evaluate parameterized module designs, freeze a point, export matching RTL."""
import argparse
import copy
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import tempfile

from model import evaluate
from module_specs import ROOT, REGISTRY, digest, library_hash, ports, resources, validate_modules, variants

FORMAT='hb-module-evaluation-v1'


def engine_hash():
    return digest({name:(ROOT/name).read_text() for name in ('model.py','module_specs.py','module_flow.py')})


def derive(design, environment):
    validate_modules(design)
    modules={m['name']:m for m in design['modules']}
    binding=design['evaluation_binding']
    if set(binding)!={'compute','sram','hb_link'}:
        raise ValueError('Evaluation binding requires compute, sram and hb_link')
    if any(n not in modules for n in binding['compute']+binding['sram']+[binding['hb_link']]):
        raise ValueError('Unknown module in evaluation binding')
    if len(binding['compute'])!=len(set(binding['compute'])) or len(binding['sram'])!=len(set(binding['sram'])):
        raise ValueError('Duplicate evaluation binding')
    for name in binding['compute']:
        if modules[name]['type']!='int_mac_array':raise ValueError('Compute binding requires implemented integer MAC arrays')
        if modules[name]['tier']!=0:raise ValueError('Current thermal adapter requires compute on tier 0 (top)')
    for name in binding['sram']:
        if modules[name]['type']!='banked_sram':raise ValueError('SRAM binding requires banked_sram')
        if modules[name]['tier']!=1:raise ValueError('Current thermal adapter requires SRAM on tier 1 (bottom)')
    link=modules[binding['hb_link']]
    if link['type']!='hb_link':raise ValueError('HB binding requires hb_link')
    if sum(m['type']=='hb_link' for m in modules.values())!=1:
        raise ValueError('Current analytical adapter supports exactly one HB link per tile')
    crossings=[c for c in design.get('connections',[]) if modules[c['source']]['tier']!=modules[c['target']]['tier']]
    if len(crossings)!=1 or binding['hb_link'] not in (crossings[0]['source'],crossings[0]['target']):
        raise ValueError('Current adapter requires exactly one explicit cross-tier stream connected to the HB module')
    if any(m['type']=='int_mac_array' and m['name'] not in binding['compute'] or
           m['type']=='banked_sram' and m['name'] not in binding['sram'] for m in modules.values()):
        raise ValueError('All MAC and SRAM instances must participate in evaluation binding')
    if not binding['compute'] or not binding['sram']:raise ValueError('Compute and SRAM bindings must not be empty')
    # Distinct models cannot masquerade as precision-specific calibration.
    widths={modules[n]['parameters']['DATA_W'] for n in binding['compute']}
    if len(widths)!=1:raise ValueError('One calibrated integer DATA_W per evaluation supported')
    if design['costs']['integer_data_width']!=next(iter(widths)):
        raise ValueError('Cost precision does not match RTL DATA_W; recalibrate costs')
    f=design['clock_hz'];tiles=design['tile_count']
    macs=sum(resources(modules[n])['macs_per_cycle'] for n in binding['compute'])
    read_bits=sum(resources(modules[n])['read_bits_per_cycle'] for n in binding['sram'])
    width=link['parameters']['WIDTH']
    cfg=copy.deepcopy(environment)
    # The emitted synchronous digital link transfers one bit per lane per cycle.
    cfg['hb']['lane_rate_gbps']=f/1e9
    a={
        'name':design['name'],'tile_count':tiles,'fixed_bits_per_tile':width,
        'endpoint_max_bits_per_tile':design['physical_limits']['endpoint_max_bits_per_tile'],
        'routing_limit_bits_per_tile':design['physical_limits']['routing_limit_bits_per_tile'],
        'peak_ops_s':2*macs*f*tiles,'sram_gbps':read_bits*f*tiles/8e9,
        # Named fabric cap remains a model boundary, not a generated router.
        'noc_gbps':design['physical_limits']['fabric_cap_gbps'],
        'startup_latency_s':(link['parameters']['STAGES']+1)/f,
        **{k:design['workload'][k] for k in ('work_ops','hb_bytes','external_bytes','external_gbps')},
        **{k:design['costs'][k] for k in ('compute_pj_op','memory_pj_hb_byte','background_top_w','background_bottom_w')}
    }
    return cfg,a


def point_payload(design,physical):
    return {'resolved_design':design,'physical':physical}


def evaluate_design(design_path,out):
    source=json.loads(design_path.read_text())
    env_path=(design_path.parent/source['environment_file']).resolve()
    environment=json.loads(env_path.read_text())
    lib_hash=library_hash();eng_hash=engine_hash()
    points=[]
    seen=set()
    if len(source['physical']['pitch_um'])*len(source['physical']['pad_modes'])>100:
        raise ValueError('Too many physical sweep points')
    for resolved in variants(source):
        cfg,architecture=derive(resolved,environment)
        for pitch,mode in itertools.product(source['physical']['pitch_um'],source['physical']['pad_modes']):
            physical={'pitch_um':pitch,'pad_mode':mode}
            payload=point_payload(resolved,physical)
            identifier=digest({'payload':payload,'environment':environment,'library':lib_hash,'engine':eng_hash})
            if identifier in seen:continue
            seen.add(identifier)
            metrics,_=evaluate(cfg,architecture,pitch,mode,'fixed_width')
            points.append({'point_id':identifier,**payload,'metrics':metrics,
                           'derived_architecture':architecture,
                           'module_resources':{m['name']:resources(m) for m in resolved['modules']}})
    data={'format':FORMAT,'library_sha256':lib_hash,'engine_sha256':eng_hash,
          'environment':environment,'source_design':source,'source_sha256':digest(source),
          'points':points,'scope':'Parameterized module benchmarks. No GPU program execution or physical signoff.'}
    out.mkdir(parents=True,exist_ok=True)
    (out/'evaluation.json').write_text(json.dumps(data,indent=2,allow_nan=False))
    lines=['# Parameterized module evaluation','','All cost/thermal values inherit the supplied calibration provenance. No physical signoff.', '',
           '| Point ID | Pitch µm | Link bits | MAC/cycle/tile | Latency ms | Energy mJ | Feasible |',
           '|---|---:|---:|---:|---:|---:|---|']
    for p in points:
        r=p['metrics'];d=p['resolved_design'];a=p['derived_architecture']
        latency=f"{r['latency_ms']:.6g}" if r['feasible'] else '—'
        energy=f"{r['energy_mj']:.6g}" if r['feasible'] else '—'
        lines.append(f"| {p['point_id'][:12]} | {r['pitch_um']} | {r['implemented_bits_per_tile']} | {a['peak_ops_s']/(2*d['clock_hz']*d['tile_count']):g} | {latency} | {energy} | {r['feasible']} |")
    (out/'EVALUATION.md').write_text('\n'.join(lines)+'\n')
    return data


def declaration(direction,name,width):
    return f"{direction} wire "+(f'[{width-1}:0] ' if width>1 else '')+name


def wrapper(m):
    name=m['name']+'_wrapper'; pp=ports(m)
    params=', '.join(f'.{k}({v})' for k,v in m['parameters'].items())
    connect=', '.join(f'.{p}({p})' for _,p,_ in pp)
    return f"module {name}(\n    "+',\n    '.join(declaration(*p) for p in pp)+f"\n);\n    {m['type']} #({params}) u_impl ({connect});\nendmodule\n"


def group_top(name,modules,connections):
    byname={m['name']:m for m in modules}
    internal=[c for c in connections if c['source'] in byname and c['target'] in byname]
    mapping={};wires=[]
    for c in internal:
        source,target=c['source'],c['target'];w=byname[source]['parameters']['WIDTH']
        prefix=f'n_{source}_to_{target}'
        wires += [f'wire [{w-1}:0] {prefix}_data;',f'wire {prefix}_valid;',f'wire {prefix}_ready;']
        for suffix in ('data','valid','ready'):
            mapping[(source,'out_'+suffix)]=prefix+'_'+suffix
            mapping[(target,'in_'+suffix)]=prefix+'_'+suffix
    pp=[('input','clk',1),('input','rst',1)]
    instances=[]
    for m in modules:
        conn=[]
        for direction,p,w in ports(m):
            if p in ('clk','rst'):signal=p
            elif (m['name'],p) in mapping:signal=mapping[m['name'],p]
            else:
                signal=m['name']+'_'+p;pp.append((direction,signal,w))
            conn.append(f'.{p}({signal})')
        instances.append(f"{m['name']}_wrapper u_{m['name']} ("+', '.join(conn)+');')
    text=f'module {name}(\n    '+',\n    '.join(declaration(*p) for p in pp)+'\n);\n'
    text+='\n'.join('    '+line for line in wires+instances)+'\nendmodule\n'
    return text,pp


def replicated_top(tile_count,tile_ports):
    # Host-visible independent tile ports. No implicit fabric, dispatcher or compiler.
    pp=[('input','clk',1),('input','rst',1)]
    body=[]
    for index in range(tile_count):
        conn=[]
        for direction,p,w in tile_ports:
            name=p if p in ('clk','rst') else f'tile{index}_{p}'
            if p not in ('clk','rst'):pp.append((direction,name,w))
            conn.append(f'.{p}({name})')
        body.append(f'lab_tile_top u_tile{index} ('+', '.join(conn)+');')
    return 'module lab_system_top(\n    '+',\n    '.join(declaration(*p) for p in pp)+'\n);\n'+'\n'.join(body)+'\nendmodule\n'


def export_point(evaluation_path,point_id,out):
    data=json.loads(evaluation_path.read_text())
    if data.get('format')!=FORMAT:
        raise ValueError('Only module evaluations can emit RTL; legacy traffic proxies have no implementation')
    if data['library_sha256']!=library_hash() or data['engine_sha256']!=engine_hash():
        raise ValueError('RTL library or evaluation engine changed; reevaluate before export')
    choices=[p for p in data['points'] if p['point_id'].startswith(point_id)]
    if len(choices)!=1:raise ValueError('Point ID must uniquely identify one evaluated configuration')
    point=choices[0];design=validate_modules(point['resolved_design']);physical=point['physical']
    expected=digest({'payload':point_payload(design,physical),'environment':data['environment'],
                     'library':library_hash(),'engine':engine_hash()})
    if expected!=point['point_id']:raise ValueError('Frozen parameters were modified after evaluation')
    cfg,architecture=derive(design,data['environment'])
    metrics,_=evaluate(cfg,architecture,physical['pitch_um'],physical['pad_mode'],'fixed_width')
    if digest(metrics)!=digest(point['metrics']) or digest(architecture)!=digest(point['derived_architecture']):
        raise ValueError('Evaluation record mismatch; refusing stale/tampered metrics')
    if not metrics['feasible']:raise ValueError('Selected configuration does not fit the HB/routing/endpoint budget')
    if out.exists():raise ValueError('Output directory already exists; choose a new directory to preserve frozen RTL')
    if design['tile_count']>64:raise ValueError('RTL replication limited to 64 tiles in this generator')
    out.parent.mkdir(parents=True,exist_ok=True)
    temp=Path(tempfile.mkdtemp(prefix='.rtl-',dir=out.parent))
    try:
        (temp/'rtl').mkdir()
        files=[]
        for kind in sorted({m['type'] for m in design['modules']}):
            filename=f'rtl/{kind}.sv';shutil.copyfile(ROOT/filename,temp/filename);files.append(filename)
        for m in design['modules']:
            filename=f"rtl/{m['name']}_wrapper.sv";(temp/filename).write_text(wrapper(m));files.append(filename)
        tile_text,tile_ports=group_top('lab_tile_top',design['modules'],design.get('connections',[]))
        (temp/'rtl/lab_tile_top.sv').write_text(tile_text);files.append('rtl/lab_tile_top.sv')
        (temp/'rtl/lab_system_top.sv').write_text(replicated_top(design['tile_count'],tile_ports));files.append('rtl/lab_system_top.sv')
        for tier in (0,1):
            mods=[m for m in design['modules'] if m['tier']==tier]
            text,_=group_top(f'lab_tier{tier}_top',mods,design.get('connections',[]))
            filename=f'rtl/lab_tier{tier}_top.sv';(temp/filename).write_text(text);files.append(filename)
        (temp/'files.f').write_text('\n'.join(files)+'\n')
        period_ns=1e9/design['clock_hz']
        (temp/'clock.sdc').write_text(f'# Target only, not proof of timing closure. Add I/O and cross-tier timing constraints.\ncreate_clock -name core_clk -period {period_ns:.9g} [get_ports clk]\n')
        for top in ('lab_system_top','lab_tile_top','lab_tier0_top','lab_tier1_top'):
            script='read_verilog -sv '+' '.join(files)+f'\nhierarchy -check -top {top}\nproc\nopt\ncheck -assert\nstat\nwrite_json {top}.json\n'
            (temp/f'check_{top}.ys').write_text(script)
        inventory=[]
        for m in design['modules']:
            inventory.append({**m,'resources':resources(m),'wrapper':m['name']+'_wrapper',
                              'system_instance_pattern':f"u_tile*/u_{m['name']}/u_impl",
                              'tier_instance':f"lab_tier{m['tier']}_top/u_{m['name']}/u_impl",
                              'calibration_key':digest({'type':m['type'],'parameters':m['parameters'],'clock_hz':design['clock_hz'],'library':library_hash()})})
        byname={m['name']:m for m in design['modules']}
        boundaries=[{**c,'payload_bits':byname[c['source']]['parameters']['WIDTH'],'handshake_bits':2}
                    for c in design.get('connections',[]) if byname[c['source']]['tier']!=byname[c['target']]['tier']]
        manifest={'format':'hb-rtl-manifest-v1','point_id':point['point_id'],
                  'library_sha256':library_hash(),'engine_sha256':engine_hash(),
                  'physical':physical,'derived_architecture':architecture,'evaluation_metrics':metrics,
                  'resolved_design':design,'environment':data['environment'],'modules':inventory,
                  'cross_tier_streams':boundaries,'top':'lab_system_top','files':files,
                  'file_sha256':{f:hashlib.sha256((temp/f).read_bytes()).hexdigest() for f in files},
                  'scope':'Digital module benchmark assembly. No GPU scheduler/NoC/PHY/CDC or foundry SRAM binding.'}
        (temp/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False))
        (temp/'README.md').write_text('# Frozen RTL candidate\n\nPoint: '+point['point_id']+'\n\n'
            'Use files.f or check_lab_system_top.ys from this directory. Each parameter is frozen in an instance wrapper.\n\n'
            'lab_system_top replicates tile benchmarks; it is not a programmable GPU. lab_tier0/1_top are per-tile partition views.\n'
            'Only explicitly declared ready/valid edges are connected. All remaining module ports are exposed for a driver/testbench.\n'
            'HB pitch/tier assignment are physical metadata, not logic parameters. Generated clock.sdc needs I/O and cross-die constraints.\n'
            'Memories are generic inferred RTL, not mapped SRAM macros. MACs are signed integers with wrapping accumulation.\n')
        temp.rename(out)
    except BaseException:
        shutil.rmtree(temp,ignore_errors=True);raise
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    ev=sub.add_parser('evaluate');ev.add_argument('--design',type=Path,required=True);ev.add_argument('--out',type=Path,required=True)
    ex=sub.add_parser('export');ex.add_argument('--evaluation',type=Path,required=True);ex.add_argument('--point',required=True);ex.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='evaluate':
        data=evaluate_design(args.design,args.out)
        print(f"{len(data['points'])} evaluated candidates, {sum(p['metrics']['feasible'] for p in data['points'])} feasible. {args.out/'EVALUATION.md'}")
    else:
        manifest=export_point(args.evaluation,args.point,args.out)
        print(f"Exported {manifest['point_id'][:12]} -> {args.out} ({len(manifest['files'])} RTL files)")


if __name__=='__main__':main()
