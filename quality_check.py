#!/usr/bin/env python3
"""Fixed, fail-closed QC pipeline and append-only execution journal for AI operators."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import numpy
import scipy

from module_specs import ROOT, digest
from optimize import load_inputs, read_json, replay, run_optimization, write_json

CHECKS = (
    ('Q01', 'input_schema_and_provenance'),
    ('Q02', 'python_regression_tests'),
    ('Q03', 'exhaustive_optimization'),
    ('Q04', 'deterministic_replay'),
    ('Q05', 'selected_rtl_integrity'),
    ('Q06', 'rtl_simulation_and_selected_parameters'),
    ('Q07', 'generic_synthesis_and_resource_match'),
    ('Q08', 'constraints_and_thermal_conservation'),
    ('Q09', 'completion_artifacts_and_source_stability'),
)


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def source_hash():
    files = list(ROOT.glob('*.py')) + list((ROOT/'rtl').glob('*.sv')) + list((ROOT/'tests').glob('*.py')) + list((ROOT/'tests').glob('*.sv'))
    return digest({str(p.relative_to(ROOT)): sha(p) for p in sorted(files)})


def runtime_versions():
    return {'python':sys.version.split()[0], 'numpy':numpy.__version__, 'scipy':scipy.__version__}


def append_jsonl(path, record):
    """One append operation, serialized with an advisory lock on Unix hosts."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(record, sort_keys=True, allow_nan=False) + '\n').encode()
    with path.open('ab', buffering=0) as stream:
        if os.name == 'posix':
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.write(payload)
        os.fsync(stream.fileno())


def check_manifest(directory):
    directory = Path(directory)
    manifest = read_json(directory/'manifest.json')
    files = (directory/'files.f').read_text().splitlines()
    if files != manifest['files'] or set(files) != set(manifest['file_sha256']):
        raise ValueError('Manifest file inventory mismatch')
    for name in files:
        file = (directory/name).resolve()
        if directory.resolve() not in file.parents or sha(file) != manifest['file_sha256'][name]:
            raise ValueError('Exported RTL changed or invalid path: '+name)
    return manifest


def run_command(command, cwd, log, timeout):
    with Path(log).open('w') as stream:
        stream.write('argv: '+json.dumps([str(s) for s in command])+'\n'); stream.flush()
        try:
            result = subprocess.run([str(s) for s in command], cwd=cwd, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f'Tool timed out after {timeout}s; inspect {log}') from error
    if result.returncode:
        raise RuntimeError(f'Command exit={result.returncode}; inspect {log}')


def selected(result):
    return next(c for c in result['candidates'] if c['point_id'] == result['selected_point_id'])


def check_physics(result):
    for candidate in result['candidates']:
        metrics = candidate['metrics']
        if metrics is None:
            continue
        tolerance = 1e-8 * max(1, metrics['power_w'])
        if metrics['heat_balance_error_w'] > tolerance or metrics['nodal_residual_w'] > tolerance:
            raise ValueError('Thermal conservation tolerance exceeded')
        if abs(metrics['energy_mj']-metrics['power_w']*metrics['latency_ms']) > 1e-10*max(1,metrics['energy_mj']):
            raise ValueError('Energy/power/latency units inconsistent')
    winner = selected(result)
    if not winner['eligible'] or winner['point_id'] not in result['pareto_ids']:
        raise ValueError('Selected point fails feasibility/Pareto check')
    for metric, bounds in result['policy']['constraints'].items():
        value = winner['metrics'][metric]
        if value is None or value < bounds.get('min', float('-inf')) or value > bounds.get('max', float('inf')):
            raise ValueError('Selected point violates '+metric)


def verify_run(directory):
    directory = Path(directory)
    record = read_json(directory/'run.json')
    if record.get('format') != 'hb-qc-run-v1' or record['status'] != 'PASS':
        raise ValueError('Run is not a completed PASS')
    if [(c['id'],c['name']) for c in record['checks']] != list(CHECKS) or any(c['status'] != 'PASS' for c in record['checks']):
        raise ValueError('Missing/reordered/failed required quality checks')
    if record['source_sha256'] != source_hash():
        raise ValueError('Source changed since this run; rerun QC (historical record remains valid for its source only)')
    if record.get('runtime_versions') != runtime_versions():
        raise ValueError('Numerical runtime versions changed; rerun QC in this environment')
    if not record.get('artifact_sha256'):
        raise ValueError('Missing artifact inventory')
    required = {'events.jsonl','QC_REPORT.md','logs/python_tests.log','search/optimization.json',
                'search/selected_rtl/manifest.json','rtl/validation.json','synthesis/synthesis_validation.json'}
    if not required <= set(record['artifact_sha256']):
        raise ValueError('Required evidence absent from audit inventory')
    for name, expected in record['artifact_sha256'].items():
        path = (directory/name).resolve()
        if directory.resolve() not in path.parents or sha(path) != expected:
            raise ValueError('Artifact was changed/missing: '+name)
    events = [json.loads(line) for line in (directory/'events.jsonl').read_text().splitlines()]
    if any(e['run_id'] != record['run_id'] or e['sequence'] != i+1 for i,e in enumerate(events)):
        raise ValueError('Journal sequence/run identity mismatch')
    expected_events = [(check, status) for check,_ in CHECKS for status in ('START','PASS')]
    if [(e['check_id'],e['status']) for e in events] != expected_events:
        raise ValueError('Journal does not show all nine completed checks')
    result = replay(directory/'search')
    manifest = check_manifest(directory/'search/selected_rtl')
    rtl = read_json(directory/'rtl/validation.json')
    synth = read_json(directory/'synthesis/synthesis_validation.json')
    pid = result['selected_point_id']
    if any(value != pid for value in (record['selected_point_id'],manifest['point_id'],rtl['candidate_point'],synth['point_id'])):
        raise ValueError('Checks refer to different selected candidates')
    binding = read_json(directory/'search/selected_rtl/optimization_binding.json')
    if binding['point_id'] != pid or binding['effective_metrics'] != selected(result)['metrics'] or binding['optimization_sha256'] != digest(result):
        raise ValueError('Effective PPA/RTL binding mismatch')
    check_physics(result)
    return record


def execute(design, policy, out, timeout=300):
    out = Path(out).resolve()
    if out.exists():
        raise ValueError('Run directory exists. Use a new directory; no overwrite/resume of QC evidence.')
    if not 1 <= timeout <= 3600:
        raise ValueError('timeout must be in [1,3600] seconds')
    out.mkdir(parents=True); (out/'logs').mkdir()
    start = utc(); run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:12]
    record = {'format':'hb-qc-run-v1','run_id':run_id,'started_utc':start,'status':'RUNNING',
              'source_sha256':source_hash(),'checks':[], 'selected_point_id':None,
              'runtime_versions':runtime_versions(), 'scope':'Software/RTL/generic synthesis QC; not PPA or thermal signoff.'}
    try:
        record['git_head'] = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip()
        record['git_dirty'] = bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True))
    except (OSError,subprocess.CalledProcessError):
        record['git_head']=None;record['git_dirty']=None
    write_json(out/'run.json',record)
    state = {}; sequence = 0
    def event(check, status, detail=''):
        nonlocal sequence
        sequence += 1
        append_jsonl(out/'events.jsonl',{'schema_version':1,'run_id':run_id,'sequence':sequence,
                     'utc':utc(),'check_id':check,'status':status,'detail':detail})
    def action(check):
        if check == 'Q01':
            state['inputs'] = load_inputs(design, policy)
        elif check == 'Q02':
            run_command([sys.executable,'-m','unittest','discover','-s','tests','-v'],ROOT,out/'logs/python_tests.log',timeout)
        elif check == 'Q03':
            result = run_optimization(design,policy,out/'search');state['result']=result
            record['selected_point_id'] = result['selected_point_id']
            if not result['selected_point_id']:
                raise ValueError('NO_FEASIBLE_SOLUTION; constraints are not automatically relaxed')
        elif check == 'Q04':
            replay(out/'search')
            for name, value in zip(('design','environment','policy','costs'),state['inputs']):
                if read_json(out/'search/inputs'/f'{name}.json') != value:
                    raise ValueError('Inputs changed during the run')
        elif check == 'Q05':
            manifest = check_manifest(out/'search/selected_rtl')
            if manifest['point_id'] != record['selected_point_id']:
                raise ValueError('Wrong candidate exported')
        elif check == 'Q06':
            run_command([sys.executable,ROOT/'check_rtl.py','--generated',out/'search/selected_rtl','--out',out/'rtl'],
                        ROOT,out/'logs/rtl.log',timeout)
            report = read_json(out/'rtl/validation.json')
            manifest = read_json(out/'search/selected_rtl/manifest.json')
            names = sorted(m['name'] for m in manifest['modules'])
            tested = sorted(c['selected_module'] for c in report['scoreboards'] if c.get('selected_module'))
            if names != tested or report['elaborated_tops'] != 4 or report['candidate_point'] != record['selected_point_id']:
                raise ValueError('Incomplete selected-parameter RTL coverage')
        elif check == 'Q07':
            run_command([sys.executable,ROOT/'check_synthesis.py','--generated',out/'search/selected_rtl','--out',out/'synthesis'],
                        ROOT,out/'logs/synthesis.log',timeout)
            report = read_json(out/'synthesis/synthesis_validation.json')
            if report['point_id'] != record['selected_point_id'] or len(report['structural_tops']) != 4:
                raise ValueError('Wrong synthesis candidate/top coverage')
        elif check == 'Q08':
            check_physics(state['result'])
        elif check == 'Q09':
            if source_hash() != record['source_sha256']:
                raise ValueError('Source changed during QC')
            for file in ('search/optimization.json','search/selected_rtl/optimization_binding.json',
                         'rtl/validation.json','synthesis/synthesis_validation.json','logs/python_tests.log'):
                if not (out/file).is_file():
                    raise ValueError('Required evidence missing: '+file)
            manifest = check_manifest(out/'search/selected_rtl')
            binding = read_json(out/'search/selected_rtl/optimization_binding.json')
            if manifest['point_id'] != record['selected_point_id'] or binding['point_id'] != record['selected_point_id']:
                raise ValueError('Final artifact candidate mismatch')
            if binding['effective_metrics'] != selected(state['result'])['metrics'] or binding['optimization_sha256'] != digest(state['result']):
                raise ValueError('Final effective PPA binding mismatch')
    try:
        for check, name in CHECKS:
            began = time.monotonic(); event(check,'START')
            print(f'{check} START {name}',flush=True)
            entry = {'id':check,'name':name,'status':'RUNNING'};record['checks'].append(entry)
            try:
                action(check)
            except BaseException as error:
                entry.update(status='FAIL',elapsed_seconds=round(time.monotonic()-began,6),detail=str(error))
                event(check,'FAIL',str(error));raise
            entry.update(status='PASS',elapsed_seconds=round(time.monotonic()-began,6))
            event(check,'PASS');print(f'{check} PASS',flush=True)
        record['status']='PASS'
    except BaseException as error:
        record['status']='FAIL';record['error']=str(error)
        for check,name in CHECKS[len(record['checks']):]:
            record['checks'].append({'id':check,'name':name,'status':'NOT_RUN'})
    record['ended_utc']=utc()
    lines=['# Fixed quality check execution report','',f"Run: {run_id}",f"Status: {record['status']}",
           f"Selected: {record['selected_point_id']}",f"Source SHA256: {record['source_sha256']}",'',
           '| ID | Check | Status | Detail |','|---|---|---|---|']
    lines += [f"| {c['id']} | {c['name']} | {c['status']} | {c.get('detail','')} |" for c in record['checks']]
    lines += ['',record['scope']]
    (out/'QC_REPORT.md').write_text('\n'.join(lines)+'\n')
    record['artifact_sha256']={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p != out/'run.json'}
    write_json(out/'run.json',record)
    append_jsonl(ROOT/'execution_logs/history.jsonl',{'schema_version':1,'utc':utc(),'run_id':run_id,
        'status':record['status'],'selected_point_id':record['selected_point_id'],'source_sha256':record['source_sha256'],
        'run_directory':os.path.relpath(out,ROOT),'run_json_sha256':sha(out/'run.json'),
        'checks':{c['id']:c['status'] for c in record['checks']}})
    print(f"{record['status']}: {out}/QC_REPORT.md",flush=True)
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    run=sub.add_parser('run');run.add_argument('--design',type=Path,required=True);run.add_argument('--policy',type=Path,required=True)
    run.add_argument('--out',type=Path,required=True);run.add_argument('--timeout-seconds',type=int,default=300)
    verify=sub.add_parser('verify');verify.add_argument('--run',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.command=='run':
            return 0 if execute(args.design,args.policy,args.out,args.timeout_seconds)['status']=='PASS' else 1
        record=verify_run(args.run);print(f"VERIFIED PASS: {record['run_id']}");return 0
    except (ValueError,KeyError,OSError,TypeError,RuntimeError) as error:
        print(f'ERROR: {error}');return 1


if __name__=='__main__':
    raise SystemExit(main())
