#!/usr/bin/env python3
"""Deterministic exhaustive constrained multi-objective optimization of module RTL candidates."""
import argparse
import itertools
import json
from pathlib import Path

from model import evaluate
from module_flow import FORMAT, derive, engine_hash, evaluate_design, export_point, point_payload
from module_specs import ROOT, digest, library_hash, resources, variants
from ppa_costs import exact_keys, number, ppa_metrics, validate_costs

METRICS = {'area_mm2', 'power_w', 'latency_ms', 'energy_mj', 'throughput_tops',
           'steady_tmax_c', 'hb_site_budget_mm2', 'pitch_um', 'timing_wns_ns',
           'sram_bytes_per_tile', 'rf_bytes_per_tile', 'fifo_bytes_per_tile'}
FORMAT_OPT = 'hb-optimization-v1'


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    def bad_constant(value):
        raise ValueError(f'Invalid JSON numeric constant {value}')
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=bad_constant)


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + '\n')


def optimizer_hash():
    return digest({name: (ROOT/name).read_text() for name in ('optimize.py', 'ppa_costs.py')})


def validate_policy(policy):
    exact_keys(policy, {'schema_version', 'selection', 'objectives', 'constraints', 'cost_model_file',
                        'max_candidates', 'quality_requirement', 'tie_breakers'})
    if type(policy['schema_version']) is not int or policy['schema_version'] != 1 or policy['selection'] not in ('weighted_sum', 'lexicographic'):
        raise ValueError('Unsupported policy version or selection method')
    if type(policy['max_candidates']) is not int or not 1 <= policy['max_candidates'] <= 4096:
        raise ValueError('max_candidates must be an integer in [1,4096]; never silently sample')
    if policy['quality_requirement'] not in ('allow_estimates', 'reported_ppa'):
        raise ValueError('Unknown quality_requirement')
    if not isinstance(policy['cost_model_file'], str) or not policy['cost_model_file']:
        raise ValueError('cost_model_file required')
    if not isinstance(policy['objectives'], list) or not policy['objectives']:
        raise ValueError('At least one objective required')
    seen = set()
    for objective in policy['objectives']:
        exact_keys(objective, {'metric', 'direction', 'scale', 'weight'})
        if objective['metric'] not in METRICS or objective['metric'] in seen:
            raise ValueError('Unknown or duplicate objective metric')
        seen.add(objective['metric'])
        if objective['direction'] not in ('min', 'max'):
            raise ValueError('direction must be min/max')
        for field in ('scale', 'weight'):
            number(objective[field], field, positive=True)
    if not isinstance(policy['constraints'], dict):
        raise ValueError('constraints must be an object')
    for metric, bounds in policy['constraints'].items():
        if metric not in METRICS:
            raise ValueError(f'Unknown constraint metric {metric}')
        exact_keys(bounds, set(), {'min', 'max'})
        if not bounds:
            raise ValueError('Constraint needs min and/or max')
        for value in bounds.values():
            number(value, metric, minimum=None)
        if bounds.get('min', float('-inf')) > bounds.get('max', float('inf')):
            raise ValueError('Constraint min exceeds max')
    if not isinstance(policy['tie_breakers'], list):
        raise ValueError('tie_breakers must be a list')
    for item in policy['tie_breakers']:
        exact_keys(item, {'metric', 'direction'})
        if item['metric'] not in METRICS or item['direction'] not in ('min', 'max'):
            raise ValueError('Invalid tie breaker')
    return policy


def space_size(source, limit):
    sizes = [len(m.get('sweep', {}).get(k, [])) for m in source['modules'] for k in m.get('sweep', {})]
    sizes += [len(source['physical']['pitch_um']), len(source['physical']['pad_modes'])]
    size = 1
    for n in sizes:
        if n <= 0:
            raise ValueError('Empty search axis')
        size *= n
    if size > limit:
        raise ValueError(f'Grid has {size} raw candidates; max_candidates={limit}. Narrow the grid explicitly.')
    if source['tile_count'] > 64:
        raise ValueError('Optimization/export currently supports at most 64 tiles')
    return size


def load_inputs(design_path, policy_path):
    design_path, policy_path = Path(design_path), Path(policy_path)
    source = read_json(design_path)
    policy = validate_policy(read_json(policy_path))
    environment = read_json(design_path.parent / source['environment_file'])
    cost = validate_costs(read_json(policy_path.parent / policy['cost_model_file']))
    space_size(source, policy['max_candidates'])
    if policy['quality_requirement'] == 'reported_ppa':
        if cost['mode'] != 'point_table' or cost['quality'] != 'reported':
            raise ValueError('reported_ppa requires a complete point_table explicitly marked reported')
        if policy['constraints'].get('timing_wns_ns', {}).get('min', -1) < 0:
            raise ValueError('reported_ppa requires timing_wns_ns.min >= 0')
    # Validate every resolved architecture before beginning expensive work.
    for design in variants(source):
        derive(design, environment)
    return source, environment, policy, cost


def verify_evaluation(data):
    if data.get('format') != FORMAT or data['library_sha256'] != library_hash() or data['engine_sha256'] != engine_hash():
        raise ValueError('Stale/incompatible module evaluation; regenerate with current source')
    if digest(data['source_design']) != data['source_sha256']:
        raise ValueError('Source snapshot mismatch')
    expected = {}
    source = data['source_design']
    for design in variants(source):
        cfg, architecture = derive(design, data['environment'])
        for pitch, mode in itertools.product(source['physical']['pitch_um'], source['physical']['pad_modes']):
            physical = {'pitch_um': pitch, 'pad_mode': mode}
            payload = point_payload(design, physical)
            pid = digest({'payload': payload, 'environment': data['environment'], 'library': library_hash(), 'engine': engine_hash()})
            metrics, _ = evaluate(cfg, architecture, pitch, mode, 'fixed_width')
            expected[pid] = {'point_id': pid, **payload, 'metrics': metrics, 'derived_architecture': architecture,
                             'module_resources': {m['name']: resources(m) for m in design['modules']}}
    actual = {p['point_id']: p for p in data['points']}
    if len(actual) != len(data['points']) or digest(actual) != digest(expected):
        raise ValueError('Evaluation coverage/content mismatch, including missing or modified candidates')


def oriented(metrics, objectives):
    return tuple((1 if o['direction'] == 'min' else -1) * metrics[o['metric']] / o['scale'] for o in objectives)


def dominates(a, b):
    return all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b))


def rank_candidates(candidates, policy):
    eligible = [c for c in candidates if c['eligible']]
    vectors = {c['point_id']: oriented(c['metrics'], policy['objectives']) for c in eligible}
    pareto = sorted(c['point_id'] for c in eligible if not any(
        dominates(vectors[other['point_id']], vectors[c['point_id']]) for other in eligible))
    def key(c):
        v = vectors[c['point_id']]
        for value in v:
            number(value, 'normalized objective', minimum=None)
        score = sum(o['weight'] * x for o, x in zip(policy['objectives'], v)) / sum(o['weight'] for o in policy['objectives'])
        number(score, 'objective score', minimum=None)
        c['score'] = score
        primary = (score, v) if policy['selection'] == 'weighted_sum' else (v,)
        tie = tuple((1 if t['direction'] == 'min' else -1) * c['metrics'][t['metric']] for t in policy['tie_breakers'])
        return primary + (tie, c['point_id'])
    ranked = sorted(eligible, key=key)
    # A positive weighted sum / lexicographic minimum must be nondominated.
    if ranked and ranked[0]['point_id'] not in pareto:
        raise ValueError('Internal error: selected candidate is dominated')
    return pareto, [c['point_id'] for c in ranked]


def solve(data, policy, cost):
    validate_policy(policy)
    validate_costs(cost)
    raw_count = space_size(data['source_design'], policy['max_candidates'])
    verify_evaluation(data)
    if policy['quality_requirement'] == 'reported_ppa' and (cost['quality'] != 'reported' or cost['mode'] != 'point_table'
            or policy['constraints'].get('timing_wns_ns', {}).get('min', -1) < 0):
        raise ValueError('reported_ppa requires reported point-table data and nonnegative timing constraint')
    candidates = []
    required = {o['metric'] for o in policy['objectives']} | set(policy['constraints']) | {t['metric'] for t in policy['tie_breakers']}
    for point in data['points']:
        metrics = ppa_metrics(point, data['environment'], cost)
        reasons = []
        if metrics is None:
            reasons.append('hb_capacity: ' + point['metrics'].get('reason', 'infeasible'))
        else:
            for metric, value in metrics.items():
                if value is not None:
                    number(value, metric, minimum=None)
            for metric in sorted(required):
                if metrics[metric] is None:
                    reasons.append(f'missing_metric:{metric}')
            for metric, bounds in policy['constraints'].items():
                if metrics[metric] is not None:
                    if 'min' in bounds and metrics[metric] < bounds['min']:
                        reasons.append(f'{metric}:below_min')
                    if 'max' in bounds and metrics[metric] > bounds['max']:
                        reasons.append(f'{metric}:above_max')
        candidates.append({'point_id': point['point_id'], 'metrics': metrics, 'eligible': not reasons, 'reasons': reasons})
    pareto, ranked = rank_candidates(candidates, policy)
    return {'format': FORMAT_OPT, 'algorithm': 'exhaustive', 'raw_grid_count': raw_count,
            'evaluated_unique_count': len(candidates), 'eligible_count': len(ranked),
            'pareto_ids': pareto, 'ranked_ids': ranked, 'selected_point_id': ranked[0] if ranked else None,
            'status': 'OPTIMAL_ON_ENUMERATED_GRID' if ranked else 'NO_FEASIBLE_SOLUTION',
            'policy': policy, 'cost_quality': cost['quality'], 'cost_provenance': cost['provenance'],
            'cost_context': cost['context'], 'cost_sha256': digest(cost), 'evaluation_sha256': digest(data),
            'optimizer_sha256': optimizer_hash(), 'candidates': candidates,
            'scope': 'Module benchmark PPA optimization; area is summed module area. Thermal remains analytical. No full GPU or signoff.'}


def run_optimization(design_path, policy_path, out):
    out = Path(out)
    if out.exists():
        raise ValueError('Output exists; use a new run directory')
    source, environment, policy, cost = load_inputs(design_path, policy_path)
    out.mkdir(parents=True)
    snapshots = out/'inputs'; snapshots.mkdir()
    for name, value in (('design', source), ('environment', environment), ('policy', policy), ('costs', cost)):
        write_json(snapshots/(name+'.json'), value)
    data = evaluate_design(Path(design_path), out/'evaluation')
    # Fail if external input files changed between validation and evaluation.
    if data['source_design'] != source or data['environment'] != environment:
        raise ValueError('Inputs changed while evaluating')
    result = solve(data, policy, cost)
    write_json(out/'optimization.json', result)
    if result['selected_point_id']:
        manifest = export_point(out/'evaluation/evaluation.json', result['selected_point_id'], out/'selected_rtl')
        selected = next(c for c in result['candidates'] if c['point_id'] == result['selected_point_id'])
        write_json(out/'selected_rtl/optimization_binding.json', {
            'point_id': manifest['point_id'], 'effective_metrics': selected['metrics'],
            'optimization_sha256': digest(result), 'cost_sha256': digest(cost),
            'note': 'Use effective_metrics for this optimization. manifest.evaluation_metrics retains the original base model.'})
    lines = ['# Optimization result', '', f"Status: {result['status']}", '',
             f"Cost quality: {cost['quality']}; {cost['provenance']}", '',
             f"Selected: {result['selected_point_id']}", '',
             '| Point | Eligible | Area mm² | Power W | Latency ms | Reason |', '|---|---|---:|---:|---:|---|']
    for c in result['candidates']:
        m = c['metrics'] or {}
        lines.append(f"| {c['point_id'][:12]} | {c['eligible']} | {m.get('area_mm2','—')} | {m.get('power_w','—')} | {m.get('latency_ms','—')} | {', '.join(c['reasons'])} |")
    (out/'OPTIMIZATION.md').write_text('\n'.join(lines)+'\n')
    return result


def replay(run):
    run = Path(run)
    stored = read_json(run/'optimization.json')
    reproduced = solve(read_json(run/'evaluation/evaluation.json'), read_json(run/'inputs/policy.json'), read_json(run/'inputs/costs.json'))
    if digest(stored) != digest(reproduced):
        raise ValueError('Optimization replay mismatch')
    return reproduced


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design', type=Path, required=True)
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_optimization(args.design, args.policy, args.out)
        print(f"{result['status']}: {result['selected_point_id']}; {args.out}/OPTIMIZATION.md")
        return 0 if result['selected_point_id'] else 2
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(f'ERROR: {error}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
