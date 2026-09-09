#!/usr/bin/env python3
"""Evaluate, optimize, export and audit the executable MTIA-like subsystem."""
import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import shutil
import sys
import uuid

from module_specs import ROOT, digest
from optimize import read_json, write_json, validate_policy, rank_candidates
from quality_check import append_jsonl, sha, source_hash, runtime_versions, utc
from mtia_model import validate_design, candidates, compile_workload, simulate
from mtia_costs import validate_costs, costs
from mtia_rtl import export as export_rtl, compile_rtl, replay_stimulus, synthesis

CHECKS=(('M01','input_and_provenance'),('M02','execution_and_exhaustive_search'),
        ('M03','all_feasible_rtl_cycle_replay'),('M04','all_feasible_generic_synthesis'),
        ('M05','deterministic_replay_and_controls'),('M06','source_and_artifact_binding'))


def engine_hash():
    files=list(ROOT.glob('mtia_*.py'))+list((ROOT/'rtl').glob('mtia_*.sv'))+[ROOT/'tests/tb_mtia.sv']
    files += [ROOT/name for name in ('module_specs.py','optimize.py','ppa_costs.py')]
    return digest({str(p.relative_to(ROOT)):sha(p) for p in sorted(files)})


def load(design,policy):
    d=validate_design(read_json(design));p=validate_policy(read_json(policy))
    c=validate_costs(read_json(Path(policy).parent/p['cost_model_file']))
    if p['quality_requirement']!='allow_estimates':raise ValueError('This architecture adapter has no reported-PPA calibration mode')
    if len(list(candidates(d)))>p['max_candidates']:raise ValueError('Grid exceeds max_candidates; never silently sample')
    return d,p,c


def evaluate(d,policy,cost):
    validate_design(d);validate_policy(policy);validate_costs(cost)
    raw=list(candidates(d))
    if len(raw)>policy['max_candidates']:raise ValueError('Grid exceeds max_candidates')
    if policy['quality_requirement']!='allow_estimates':raise ValueError('Reported PPA unsupported in this adapter')
    required={o['metric'] for o in policy['objectives']}|set(policy['constraints'])|{o['metric'] for o in policy['tie_breakers']}
    points=[];details={};engine=engine_hash()
    for candidate in raw:
        pid=digest({'design':d,'candidate':candidate,'engine':engine})
        point={'point_id':pid,'candidate':candidate,'metrics':None,'eligible':False,'reasons':[],'workloads':{}}
        if not candidate['geometric_feasible']:
            point['reasons']=['hb_capacity'];points.append(point);continue
        runs={}
        for w in d['workloads']:
            result=simulate(d,candidate,w);adapter=costs(d,candidate,result,cost)
            runs[w['name']]={'execution':result,'cost':adapter}
            point['workloads'][w['name']]={'cycles':result['cycles'],'metrics':adapter['metrics'],
                'counts':result['counts'],'stalls':result['stalls'],'execution_sha256':digest(result),
                'cost_sha256':digest(adapter)}
        metrics=dict(next(iter(runs.values()))['cost']['metrics'])
        metrics['latency_ms']=sum(r['cost']['metrics']['latency_ms'] for r in runs.values())
        metrics['energy_mj']=sum(r['cost']['metrics']['energy_mj'] for r in runs.values())
        metrics['power_w']=metrics['energy_mj']/metrics['latency_ms']
        for key in ('top_power_w','bottom_power_w'):
            metrics[key]=sum(r['cost']['metrics'][key]*r['cost']['metrics']['latency_ms'] for r in runs.values())/metrics['latency_ms']
        metrics['throughput_tops']=sum(r['execution']['useful_ops'] for r in runs.values())/(metrics['latency_ms']*1e9)
        for key in ('steady_tmax_c','nodal_residual_w','heat_balance_error_w'):
            metrics[key]=max(r['cost']['metrics'][key] for r in runs.values())
        for key in sorted(required):
            value=metrics.get(key)
            if value is None:point['reasons'].append('missing_metric:'+key)
            else:
                limits=policy['constraints'].get(key,{})
                if value<limits.get('min',-math.inf) or value>limits.get('max',math.inf):point['reasons'].append('constraint:'+key)
        point.update(metrics=metrics,eligible=not point['reasons']);points.append(point);details[pid]=runs
    pareto,ranked=rank_candidates(points,policy)
    return {'format':'mtia-evaluation-v1','engine_sha256':engine,'design':d,'policy':policy,'costs':cost,
            'raw_grid_count':len(points),'geometric_feasible_count':len(details),'eligible_count':len(ranked),
            'pareto_ids':pareto,'ranked_ids':ranked,'selected_point_id':ranked[0] if ranked else None,
            'candidates':points,'comparison':comparison(points,d),
            'scope':'Suite latency/energy are summed; power is energy/time; Tmax is max of per-workload steady cell means. Uncalibrated.'},details


def comparison(points,d):
    """Mechanistic comparisons use geometric feasibility, independent of PPA policy.

    Never label these as policy-selected optima. Fixed-width controls isolate
    pitch from the architecture changes that width reoptimization permits.
    """
    rows=[];fixed=[]
    feasible=[p for p in points if p['metrics'] is not None]
    for w in d['workloads']:
        name=w['name']
        for partition in ('2d','coarse','local_scratch'):
            groups=defaultdict(list)
            for p in feasible:
                if p['candidate']['partition']==partition:groups[p['candidate']['pitch_um']].append(p)
            for pitch,group in sorted(groups.items(),reverse=True):
                winner=min(group,key=lambda p:(p['workloads'][name]['cycles'],p['candidate']['hb_bits'],p['point_id']))
                rows.append({'workload':name,'partition':partition,'pitch_um':pitch,
                             'width_bits':winner['candidate']['hb_bits'],'cycles':winner['workloads'][name]['cycles'],
                             'point_id':winner['point_id']})
        by_width=defaultdict(list)
        for p in feasible:
            c=p['candidate']
            if c['partition']=='local_scratch':by_width[c['hb_bits']].append(p)
        for width,group in sorted(by_width.items()):
            if len(group)>1:
                cycles={p['workloads'][name]['cycles'] for p in group}
                if len(cycles)!=1:raise ValueError('Fixed-width pitch control changed logical timing')
                fixed.append({'workload':name,'width_bits':width,'pitches_um':sorted(p['candidate']['pitch_um'] for p in group),
                              'cycles':cycles.pop(),'status':'PASS'})
    return {'selection':'minimum cycles among geometrically feasible widths; not the PPA policy selection',
            'reoptimized_width':rows,'fixed_width_controls':fixed,
            'baseline_2d':'Ideal direct same-die wires (zero transport latency); no planar routing extraction.'}


def coverage():
    return {
        'architecture':'mtia-like-int8-v1','representation_status':'EXPLORATORY',
        'reference':'https://engineering.fb.com/2026/08/24/networking-traffic/mtia-300-meta-training-chip-built-in-nics/',
        'reference_date':'2026-08-24',
        'features':{
            'dot_product':'mtia_pe: signed INT8 vector dot, wrapping INT32 accumulator',
            'vector_sfu_subset':'mtia_pe: add_sum and relu_sum only',
            'scratch_dma':'mtia_scratch: synchronous 2R1W byte banks; cluster DMA loader',
            'local_writeback':'result transport and round-robin arbiter feed shared SRAM',
            'message_engine_nmc':'mtia_me_nmc: occupied-bit dependency, local+NIC reduction, concurrent with PEs',
            'partition_controls':'2D direct wires; coarse DMA/results; local requests/operands/results'},
        'omissions':['RISC-V ISA/firmware','FP8/BF16/MX precision','full SFU/softmax','full PE mesh/NoC',
                     'bank-conflict model for other port organizations','RDMA/NIC protocol and network topology',
                     'foundry SRAM/Liberty/HB RC','package/HBM/NIC power','APR/STA/FEM calibration'],
        'checks':[
            {'id':'R01','status':'PARTIAL','scope':'Documented subsystem features and explicit omissions; not full MTIA coverage'},
            {'id':'R02','status':'PASS','scope':'Executed supported integer kernels vs independent scalar oracle'},
            {'id':'R03','status':'PASS','scope':'Every feasible candidate/workload vs exported RTL cycle replay; not silicon timing'},
            {'id':'R04','status':'NOT_CALIBRATED','scope':'No independent foundry PPA holdout data'},
            {'id':'R05','status':'NOT_CALIBRATED','scope':'Synthetic cell thermal network; no physical calibration'},
            {'id':'R06','status':'PARTIAL','scope':'Fixed-width controls and external-bottleneck experiments; no calibrated uncertainty model'}]}


def check_evaluation(evaluation,details):
    for point in evaluation['candidates']:
        if point['metrics'] is None:continue
        for name,r in details[point['point_id']].items():
            execution=r['execution'];m=r['cost']['metrics']
            if execution['correctness']!='PASS':raise ValueError('Kernel correctness missing')
            if not math.isclose(m['energy_mj'],m['power_w']*m['latency_ms'],rel_tol=1e-12):raise ValueError('Energy units inconsistent')
            if max(m['nodal_residual_w'],m['heat_balance_error_w'])>1e-8*max(1,m['power_w']):raise ValueError('Thermal residual too large')
            if digest(execution)!=point['workloads'][name]['execution_sha256'] or digest(r['cost'])!=point['workloads'][name]['cost_sha256']:
                raise ValueError('Workload detail binding mismatch')
    pid=evaluation['selected_point_id']
    if pid is None or pid not in evaluation['pareto_ids']:raise ValueError('No feasible nondominated selection; constraints unchanged')


def save_search(out,evaluation,details):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    write_json(out/'evaluation.json',evaluation)
    d=evaluation['design']
    for w in d['workloads']:write_json(out/(w['name']+'_program.json'),compile_workload(d['parameters'],w))
    for point in evaluation['candidates']:
        pid=point['point_id']
        if pid not in details:continue
        dest=out/'points'/pid;dest.mkdir(parents=True)
        for name,result in details[pid].items():write_json(dest/(name+'.json'),result)
        export_rtl(d,point['candidate'],pid,dest/'rtl',evaluation['engine_sha256'])
    pid=evaluation['selected_point_id']
    if pid:
        shutil.copytree(out/'points'/pid/'rtl',out/'selected_rtl')
        selected=next(p for p in evaluation['candidates'] if p['point_id']==pid)
        write_json(out/'selected_rtl/optimization_binding.json',{'point_id':pid,'evaluation_sha256':digest(evaluation),
                   'effective_metrics':selected['metrics'],'per_workload':selected['workloads']})
    lines=['# MTIA-like architecture comparison','',evaluation['scope'],'',
           f"Cost quality: {evaluation['costs']['quality']}; selected: {pid}",
           f"Raw: {evaluation['raw_grid_count']}; geometry feasible: {evaluation['geometric_feasible_count']}; eligible: {evaluation['eligible_count']}; Pareto: {len(evaluation['pareto_ids'])}",'',
           'Minimum cycles among geometrically feasible widths. This table is not the PPA policy selection.','',
           '| Workload | Partition | Pitch µm | Width bits | Cycles |','|---|---|---:|---:|---:|']
    lines += [f"| {r['workload']} | {r['partition']} | {r['pitch_um']} | {r['width_bits']} | {r['cycles']} |" for r in evaluation['comparison']['reoptimized_width']]
    lines += ['','2D uses ideal direct same-die wires. No physical routing, FPGA/ASIC frequency or vendor speedup is inferred.']
    (out/'COMPARISON.md').write_text('\n'.join(lines)+'\n')


def replay_search(out):
    out=Path(out);saved=read_json(out/'evaluation.json')
    if saved['format']!='mtia-evaluation-v1' or saved['engine_sha256']!=engine_hash():raise ValueError('Stale architecture engine; evaluate again')
    fresh,details=evaluate(saved['design'],saved['policy'],saved['costs'])
    if digest(fresh)!=digest(saved):raise ValueError('Evaluation, candidates or metrics were modified')
    check_evaluation(fresh,details)
    for pid,runs in details.items():
        for name,result in runs.items():
            if digest(read_json(out/'points'/pid/(name+'.json')))!=digest(result):raise ValueError('Detailed execution/trace changed')
    return fresh,details


def execute(design,policy,out):
    out=Path(out).resolve()
    if out.exists():raise ValueError('Output exists. Use a new run; never overwrite evidence')
    out.mkdir(parents=True);rid=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:12]
    record={'format':'mtia-qc-v1','run_id':rid,'status':'RUNNING','started_utc':utc(),'source_sha256':source_hash(),
            'runtime_versions':runtime_versions(),'checks':[],'selected_point_id':None}
    write_json(out/'run.json',record);seq=0;state={}
    def event(cid,status,detail=''):
        nonlocal seq
        seq+=1;append_jsonl(out/'events.jsonl',{'run_id':rid,'sequence':seq,'utc':utc(),'check_id':cid,'status':status,'detail':detail})
    def action(cid):
        if cid=='M01':
            d,p,c=load(design,policy);state.update(design=d,policy=p,costs=c)
            (out/'inputs').mkdir()
            for name,data in (('design',d),('policy',p),('costs',c)):write_json(out/'inputs'/f'{name}.json',data)
        elif cid=='M02':
            e,details=evaluate(state['design'],state['policy'],state['costs']);state.update(e=e,details=details)
            record['selected_point_id']=e['selected_point_id'];save_search(out/'search',e,details);check_evaluation(e,details)
        elif cid=='M03':
            checks=[];d=state['design']
            for point in state['e']['candidates']:
                if point['metrics'] is None:continue
                pid=point['point_id'];dest=out/'rtl_validation'/pid
                image=compile_rtl(d,point['candidate'],dest,out/'search/points'/pid/'rtl')
                for w in d['workloads']:
                    result,stim=simulate(d,point['candidate'],w,True)
                    if digest(result)!=point['workloads'][w['name']]['execution_sha256']:raise ValueError('Stimulus diverged from evaluated model')
                    checks.append({'point_id':pid,'workload':w['name'],**replay_stimulus(image,stim,dest/w['name'])})
            write_json(out/'rtl_validation.json',{'cases':checks,'status':'PASS'})
        elif cid=='M04':
            checks=[]
            for point in state['e']['candidates']:
                if point['metrics'] is None:continue
                pid=point['point_id'];checks.append(synthesis(out/'search/points'/pid/'rtl',out/'synthesis'/pid))
            write_json(out/'synthesis.json',{'cases':checks,'status':'PASS'})
        elif cid=='M05':
            replay_search(out/'search')
            if load(design,policy)!=(state['design'],state['policy'],state['costs']):raise ValueError('Input files changed during run')
            # The representation report is only written after model/RTL checks succeed.
            write_json(out/'representation.json',coverage())
        elif cid=='M06':
            if record['source_sha256']!=source_hash():raise ValueError('Source changed during run')
            e=state['e'];expected={(p['point_id'],w['name']) for p in e['candidates'] if p['metrics'] is not None for w in e['design']['workloads']}
            actual={(r['point_id'],r['workload']) for r in read_json(out/'rtl_validation.json')['cases'] if r['status']=='PASS'}
            if expected!=actual:raise ValueError('Missing RTL workload coverage')
            from quality_check import check_manifest
            for point in e['candidates']:
                if point['metrics'] is not None:check_manifest(out/'search/points'/point['point_id']/'rtl')
            check_manifest(out/'search/selected_rtl')
            binding=read_json(out/'search/selected_rtl/optimization_binding.json')
            if binding['evaluation_sha256']!=digest(e):raise ValueError('Selected RTL/result binding mismatch')
    try:
        for cid,name in CHECKS:
            event(cid,'START');print(cid+' START '+name,flush=True)
            entry={'id':cid,'name':name,'status':'RUNNING'};record['checks'].append(entry)
            try:action(cid)
            except BaseException as error:
                entry.update(status='FAIL',detail=str(error));event(cid,'FAIL',str(error));raise
            entry['status']='PASS';event(cid,'PASS');print(cid+' PASS',flush=True)
        record['status']='PASS'
    except BaseException as error:
        record.update(status='FAIL',error=str(error))
        record['checks'] += [{'id':cid,'name':name,'status':'NOT_RUN'} for cid,name in CHECKS[len(record['checks']):]]
    record['ended_utc']=utc()
    lines=['# Executable MTIA-like subsystem QC','',f'Run: {rid}',f"Status: {record['status']}",
           f"Selected: {record['selected_point_id']}",'','| Check | Status | Detail |','|---|---|---|']
    lines += [f"| {r['id']} {r['name']} | {r['status']} | {r.get('detail','')} |" for r in record['checks']]
    lines += ['','Software/RTL cycle validation only. R01/R06 partial; R04/R05 uncalibrated. See representation.json when available.']
    (out/'QC_REPORT.md').write_text('\n'.join(lines)+'\n')
    record['artifact_sha256']={str(f.relative_to(out)):sha(f) for f in sorted(out.rglob('*')) if f.is_file() and f!=out/'run.json'}
    write_json(out/'run.json',record)
    append_jsonl(ROOT/'execution_logs/mtia_history.jsonl',{'schema_version':1,'run_id':rid,'utc':utc(),'status':record['status'],
        'run_directory':os.path.relpath(out,ROOT),'run_json_sha256':sha(out/'run.json'),'source_sha256':record['source_sha256'],
        'selected_point_id':record['selected_point_id'],'checks':{r['id']:r['status'] for r in record['checks']}})
    print(record['status']+': '+str(out/'QC_REPORT.md'),flush=True);return record


def verify(out):
    out=Path(out).resolve();record=read_json(out/'run.json')
    if record.get('format')!='mtia-qc-v1' or record['status']!='PASS':raise ValueError('Run is not a completed PASS')
    if [(r['id'],r['name']) for r in record['checks']]!=list(CHECKS) or any(r['status']!='PASS' for r in record['checks']):raise ValueError('Incomplete checks')
    if record['source_sha256']!=source_hash() or record['runtime_versions']!=runtime_versions():raise ValueError('Source/runtime changed; rerun')
    required={'inputs/design.json','inputs/policy.json','inputs/costs.json','events.jsonl','QC_REPORT.md','search/evaluation.json',
              'search/selected_rtl/manifest.json','search/selected_rtl/optimization_binding.json','rtl_validation.json','synthesis.json','representation.json'}
    if not required<=set(record['artifact_sha256']):raise ValueError('Required artifact missing from inventory')
    for name,expected in record['artifact_sha256'].items():
        path=(out/name).resolve()
        if out not in path.parents or not path.is_file() or sha(path)!=expected:raise ValueError('Artifact changed/missing: '+name)
    events=[json.loads(line) for line in (out/'events.jsonl').read_text().splitlines()]
    if [(e['check_id'],e['status']) for e in events]!=[(cid,s) for cid,_ in CHECKS for s in ('START','PASS')]:raise ValueError('Journal order/status mismatch')
    if any(e['run_id']!=record['run_id'] or e['sequence']!=j+1 for j,e in enumerate(events)):raise ValueError('Journal identity mismatch')
    e,details=replay_search(out/'search')
    if record['selected_point_id']!=e['selected_point_id']:raise ValueError('Selected point mismatch')
    for name,value in (('design',e['design']),('policy',e['policy']),('costs',e['costs'])):
        if read_json(out/'inputs'/f'{name}.json')!=value:raise ValueError('Frozen inputs disagree')
    from quality_check import check_manifest
    check_manifest(out/'search/selected_rtl')
    for point in e['candidates']:
        if point['metrics'] is not None:check_manifest(out/'search/points'/point['point_id']/'rtl')
    if read_json(out/'representation.json')!=coverage():raise ValueError('Representation report mismatch')
    binding=read_json(out/'search/selected_rtl/optimization_binding.json')
    selected=next(p for p in e['candidates'] if p['point_id']==e['selected_point_id'])
    if binding!={'point_id':selected['point_id'],'evaluation_sha256':digest(e),'effective_metrics':selected['metrics'],'per_workload':selected['workloads']}:raise ValueError('Selected result binding changed')
    expected={(p['point_id'],w['name']) for p in e['candidates'] if p['metrics'] is not None for w in e['design']['workloads']}
    cases=read_json(out/'rtl_validation.json')['cases']
    if len(cases)!=len(expected) or {(r['point_id'],r['workload']) for r in cases if r['status']=='PASS'}!=expected:raise ValueError('Incomplete RTL coverage')
    for r in cases:
        if r['cycles']!=details[r['point_id']][r['workload']]['execution']['cycles']:raise ValueError('RTL cycle count disagrees')
    syn=read_json(out/'synthesis.json')['cases']
    ids={pid for pid,_ in expected}
    if len(syn)!=len(ids) or {r['point_id'] for r in syn if r['status']=='PASS'}!=ids:raise ValueError('Incomplete synthesis coverage')
    p=e['design']['parameters']
    for r in syn:
        if r['multipliers']!=p['pes']*p['lanes'] or r['memory_bits']!=p['pes']*p['lanes']*8*p['scratch_rows']+p['shared_entries']*32:
            raise ValueError('Synthesis resource mismatch')
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__);subs=parser.add_subparsers(dest='command',required=True)
    for name in ('run','evaluate'):
        s=subs.add_parser(name);s.add_argument('--design',type=Path,required=True);s.add_argument('--policy',type=Path,required=True);s.add_argument('--out',type=Path,required=True)
    s=subs.add_parser('verify');s.add_argument('--run',type=Path,required=True)
    s=subs.add_parser('export');s.add_argument('--run',type=Path,required=True);s.add_argument('--point',required=True);s.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.command=='run':return 0 if execute(args.design,args.policy,args.out)['status']=='PASS' else 1
        if args.command=='verify':record=verify(args.run);print('VERIFIED PASS: '+record['run_id']);return 0
        if args.command=='evaluate':
            if args.out.exists():raise ValueError('Output exists')
            d,p,c=load(args.design,args.policy);e,details=evaluate(d,p,c);save_search(args.out,e,details)
            print('EXPLORATORY: '+str(args.out/'COMPARISON.md'));return 0 if e['selected_point_id'] else 2
        verify(args.run);e,_=replay_search(args.run/'search')
        matches=[p for p in e['candidates'] if p['point_id'].startswith(args.point)]
        if not args.point or len(matches)!=1 or not matches[0]['eligible']:raise ValueError('Need one eligible point ID')
        point=matches[0];export_rtl(e['design'],point['candidate'],point['point_id'],args.out,e['engine_sha256'])
        write_json(args.out/'optimization_binding.json',{'point_id':point['point_id'],'evaluation_sha256':digest(e),'effective_metrics':point['metrics'],'per_workload':point['workloads']})
        print('EXPORTED: '+str(args.out));return 0
    except (ValueError,RuntimeError,OSError,KeyError,TypeError) as error:
        print('ERROR: '+str(error),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
