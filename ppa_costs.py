"""Explicit PPA cost adapters. Area means summed module cell/macro area, not die footprint."""
import copy
import math

from model import build_thermal, distribute_power, evaluate
from module_flow import derive
from module_specs import REGISTRY, resources

COEFFICIENTS = ('base', 'memory_bits', 'state_bits', 'macs_per_cycle')


def number(value, name, minimum=0, positive=False):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    if minimum is not None and (value < minimum or (positive and value == minimum)):
        raise ValueError(f'{name} outside allowed range')
    return value


def exact_keys(obj, required, optional=()):
    if not isinstance(obj, dict) or not set(required) <= set(obj) or set(obj) - set(required) - set(optional):
        raise ValueError(f'Expected keys {sorted(required)}; optional {sorted(optional)}')


def validate_costs(cost):
    exact_keys(cost, {'schema_version', 'mode', 'quality', 'provenance', 'context'}, {'modules', 'entries'})
    if type(cost['schema_version']) is not int or cost['schema_version'] != 1 or cost['mode'] not in ('resource_estimate', 'point_table'):
        raise ValueError('Unsupported cost schema/mode')
    if cost['quality'] not in ('synthetic', 'estimated', 'reported'):
        raise ValueError('Cost quality must be synthetic, estimated or reported')
    if not isinstance(cost['provenance'], str) or not cost['provenance'].strip():
        raise ValueError('Cost provenance required')
    exact_keys(cost['context'], {'process', 'corner', 'voltage_v', 'temperature_c', 'flow'})
    for key in ('process', 'corner', 'flow'):
        if not isinstance(cost['context'][key], str) or not cost['context'][key].strip():
            raise ValueError(f'Nonempty context.{key} required')
    number(cost['context']['voltage_v'], 'voltage_v', positive=True)
    number(cost['context']['temperature_c'], 'temperature_c', minimum=-273.15, positive=True)
    if cost['mode'] == 'resource_estimate':
        if cost['quality'] == 'reported' or 'entries' in cost:
            raise ValueError('Resource estimates cannot claim reported PPA')
        exact_keys(cost.get('modules'), set(REGISTRY))
        for kind, entry in cost['modules'].items():
            exact_keys(entry, {'area_um2', 'extra_idle_w'})
            for field in ('area_um2', 'extra_idle_w'):
                exact_keys(entry[field], set(COEFFICIENTS))
                for key, value in entry[field].items():
                    number(value, f'{kind}.{field}.{key}')
    else:
        if 'modules' in cost or not isinstance(cost.get('entries'), list) or not cost['entries']:
            raise ValueError('Point-table entries required')
        seen = set()
        for entry in cost['entries']:
            exact_keys(entry, {'point_id', 'area_mm2', 'latency_ms', 'top_power_w',
                               'bottom_power_w', 'timing_wns_ns', 'source'})
            pid = entry['point_id']
            if not isinstance(pid, str) or len(pid) != 64 or any(c not in '0123456789abcdef' for c in pid) or pid in seen:
                raise ValueError('Point-table IDs must be unique full SHA256 IDs')
            seen.add(pid)
            for key in ('area_mm2', 'latency_ms'):
                number(entry[key], key, positive=True)
            for key in ('top_power_w', 'bottom_power_w'):
                number(entry[key], key)
            number(entry['timing_wns_ns'], 'timing_wns_ns', minimum=None)
            if not isinstance(entry['source'], str) or not entry['source'].strip():
                raise ValueError('Each point-table row needs a source reference')
    return cost


def ppa_metrics(point, environment, cost):
    """Return effective metrics without modifying the frozen base evaluation."""
    if not point['metrics']['feasible']:
        return None
    design = point['resolved_design']
    cfg, architecture = derive(design, environment)
    physical = point['physical']
    if cost['mode'] == 'resource_estimate':
        area = 0.0
        extra = [0.0, 0.0]
        for module in design['modules']:
            res = resources(module)
            features = {'base': 1, **{k: res[k] for k in COEFFICIENTS if k != 'base'}}
            entry = cost['modules'][module['type']]
            area += sum(features[k] * entry['area_um2'][k] for k in COEFFICIENTS)
            extra[module['tier']] += sum(features[k] * entry['extra_idle_w'][k] for k in COEFFICIENTS)
        tiles = design['tile_count']
        architecture = copy.deepcopy(architecture)
        architecture['background_top_w'] += extra[0] * tiles
        architecture['background_bottom_w'] += extra[1] * tiles
        result, _ = evaluate(cfg, architecture, physical['pitch_um'], physical['pad_mode'], 'fixed_width')
        area = area * tiles / 1e6
        number(area, 'Total module area', positive=True)
        timing = None  # No fabricated frequency/STA result for analytical costs.
    else:
        entries = {entry['point_id']: entry for entry in cost['entries']}
        if point['point_id'] not in entries:
            raise ValueError(f'Missing point-table PPA for geometrically feasible point {point["point_id"]}; no fallback')
        entry = entries[point['point_id']]
        result = copy.deepcopy(point['metrics'])
        area, timing = entry['area_mm2'], entry['timing_wns_ns']
        result['latency_ms'] = entry['latency_ms']
        result['top_power_w'] = entry['top_power_w']
        result['bottom_power_w'] = entry['bottom_power_w']
        result['total_power_w'] = entry['top_power_w'] + entry['bottom_power_w']
        result['energy_mj'] = result['total_power_w'] * entry['latency_ms']
        result['throughput_tops'] = design['workload']['work_ops'] / (entry['latency_ms'] * 1e9)
        network = build_thermal(cfg['thermal'], result['interface_r_m2k_w'])
        power = distribute_power(entry['top_power_w'], entry['bottom_power_w'], cfg['thermal'])
        temps = network.steady(power)
        result['steady_tmax_c'] = float(temps.max())
        result.update(network.residuals(temps, power))
    # Expose only well-defined optimization metrics, not stale base-model temperatures.
    return {
        'area_mm2': area, 'power_w': result['total_power_w'],
        'latency_ms': result['latency_ms'], 'energy_mj': result['energy_mj'],
        'throughput_tops': result['throughput_tops'], 'steady_tmax_c': result['steady_tmax_c'],
        'top_power_w': result['top_power_w'], 'bottom_power_w': result['bottom_power_w'],
        'hb_site_budget_mm2': result['hb_site_budget_mm2'], 'pitch_um': physical['pitch_um'],
        'timing_wns_ns': timing, 'heat_balance_error_w': result['heat_balance_error_w'],
        'nodal_residual_w': result['nodal_residual_w'],
        **{label: sum(resources(m)['memory_bits'] for m in design['modules'] if m['type'] == kind)/8
           for label, kind in (('sram_bytes_per_tile','banked_sram'), ('rf_bytes_per_tile','register_file'),
                               ('fifo_bytes_per_tile','stream_fifo'))},
    }
