#!/usr/bin/env python3
"""Run: python3 run.py --config examples/demo.json --out results/demo"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
import numpy as np
from model import hb_geometry, evaluate, build_thermal, distribute_power


def save_csv(path, rows):
    fields = sorted(set().union(*(r.keys() for r in rows)))
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def plots(config, rows, thermal_rows, detail, out):
    cache = (out/'.cache').resolve()
    cache.mkdir(exist_ok=True)
    os.environ.setdefault('MPLCONFIGDIR', str(cache/'matplotlib'))
    os.environ.setdefault('XDG_CACHE_HOME', str(cache))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    fig, axs = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    metrics = [('latency_ms', 'Optimistic workload latency (ms)'), ('energy_mj', 'Modeled energy (mJ)'),
               ('hb_site_budget_mm2', 'HB site allocation budget (mm²)'), ('steady_tmax_c', 'Repeated-workload steady Tmax (°C)')]
    for ax, (metric, label) in zip(axs.flat, metrics):
        for arch in config['architectures']:
            for mode, style in [('width_sweep', '-'), ('fixed_width', '--')]:
                subset = sorted((r for r in rows if r['feasible'] and r['architecture'] == arch['name']
                                 and r['pad_mode'] == 'constant_fill' and r['link_mode'] == mode), key=lambda r:r['pitch_um'])
                ax.plot([r['pitch_um'] for r in subset], [r[metric] for r in subset], style+'o',
                        label=arch['name']+' / '+mode, markersize=4)
        ax.set_xscale('log', base=2)
        ax.set_xticks(sorted(config['pitch_um']))
        ax.set_xticklabels([f'{p:g}' for p in sorted(config['pitch_um'])])
        ax.set_xlabel('HB pitch (µm)')
        ax.set_ylabel(label)
        ax.grid(alpha=.2)
    axs[0, 0].legend(fontsize=7)
    fig.suptitle('HB Pitch Lab v0.1 — SYNTHETIC ASSUMPTIONS, NOT FOUNDRY PPA\nConstant Cu fill; width sweep is not architecture optimization', fontsize=12)
    fig.savefig(out/'sweep.png', dpi=180)
    fig.savefig(out/'sweep.svg')
    plt.close(fig)
    fig, axs = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    for mode in config['pad_modes']:
        subset = sorted((r for r in thermal_rows if r['pad_mode'] == mode), key=lambda r:r['pitch_um'])
        axs[0].plot([r['pitch_um'] for r in subset], [r['cu_fill_fraction'] for r in subset], 'o-', label=mode)
        axs[1].plot([r['pitch_um'] for r in subset], [r['steady_tmax_c'] for r in subset], 'o-', label=mode)
    for ax in axs:
        ax.set_xscale('log', base=2); ax.set_xlabel('HB pitch (µm)'); ax.grid(alpha=.2); ax.legend(fontsize=8)
        ax.set_xticks(sorted(config['pitch_um']))
        ax.set_xticklabels([f'{p:g}' for p in sorted(config['pitch_um'])])
    axs[0].set_ylabel('Interface-average Cu area fraction')
    axs[1].set_ylabel('Steady Tmax (°C)')
    fig.suptitle('Thermal control: fixed map, 80 W top + 20 W bottom\nHomogenized interface; no local pad spreading physics', fontsize=12)
    fig.savefig(out/'thermal_control.png', dpi=180)
    fig.savefig(out/'thermal_control.svg')
    plt.close(fig)
    network, power, temperature = detail
    fig, axs = plt.subplots(1, 2, figsize=(9, 4), constrained_layout=True)
    for tier, ax in enumerate(axs):
        values = temperature.reshape(2, network.grid_n, network.grid_n)[tier]
        im = ax.imshow(values, vmin=temperature.min(), vmax=temperature.max(), cmap='inferno')
        ax.set_title(('Near cooler', 'Base die')[tier]); ax.set_xlabel('Grid column'); ax.set_ylabel('Grid row')
    fig.colorbar(im, ax=list(axs), label='Temperature (°C)')
    fig.suptitle('Synthetic fixed-power control, smallest pitch / constant Cu fill')
    fig.savefig(out/'thermal_map.png', dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(__file__).parent/'examples/demo.json')
    parser.add_argument('--out', type=Path, default=Path(__file__).parent/'results/demo')
    args = parser.parse_args()
    raw = args.config.read_bytes()
    cfg = json.loads(raw)
    if not cfg.get('provenance'):
        raise ValueError('A provenance statement is required')
    rows = []
    for arch in cfg['architectures']:
        for pad in cfg['pad_modes']:
            for mode in cfg['link_modes']:
                for pitch in cfg['pitch_um']:
                    row, _ = evaluate(cfg, arch, pitch, pad, mode)
                    rows.append(row)
    control = []
    for pad in cfg['pad_modes']:
        for pitch in cfg['pitch_um']:
            geometry = hb_geometry(pitch, cfg['hb'], pad)
            net = build_thermal(cfg['thermal'], geometry['interface_r_m2k_w'])
            power = distribute_power(80, 20, cfg['thermal'])
            temperature = net.steady(power)
            control.append(dict(pad_mode=pad, pitch_um=pitch, steady_tmax_c=float(temperature.max()),
                                **geometry, **net.residuals(temperature, power)))
    # Fixed-power pulse, not the thermal evolution of a particular GPU kernel.
    geometry = hb_geometry(min(cfg['pitch_um']), cfg['hb'], 'constant_fill')
    net = build_thermal(cfg['thermal'], geometry['interface_r_m2k_w'])
    power = distribute_power(80, 20, cfg['thermal'])
    temperatures = net.steady(power)
    times, trace = net.transient(power, duration_s=.05, dt_s=.0002)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'input_snapshot.json').write_bytes(raw)
    code_hash = hashlib.sha256((Path(__file__).read_bytes()+Path(__file__).with_name('model.py').read_bytes())).hexdigest()
    output = {'version':'0.1.0', 'input_sha256':hashlib.sha256(raw).hexdigest(), 'engine_sha256':code_hash,
              'python':sys.version, 'numpy':np.__version__, 'provenance':cfg['provenance'],
              'model_status':'Uncalibrated analytical prototype. See README limitations.',
              'sweep':rows, 'fixed_power_thermal_control':control,
              'fixed_power_temperature_grid_c':temperatures.reshape(2, net.grid_n, net.grid_n).tolist()}
    (args.out/'results.json').write_text(json.dumps(output, indent=2, allow_nan=False), encoding='utf-8')
    save_csv(args.out/'sweep.csv', rows)
    save_csv(args.out/'thermal_control.csv', control)
    save_csv(args.out/'fixed_power_transient.csv', [{'time_s':float(t), 'tmax_c':float(v.max())} for t,v in zip(times,trace)])
    plots(cfg, rows, control, (net,power,temperatures), args.out)
    valid = [r for r in rows if r['feasible']]
    error = max(r['heat_balance_error_w'] for r in valid+control)
    summary = ['# HB Pitch Lab — example run', '', '**Synthetic parameters; not measured or calibrated SoIC results.**', '',
               f"Evaluated {len(rows)} points; {len(valid)} feasible under the simplified connection budgets.",
               f"Maximum steady heat-balance residual: {error:.3g} W.", '',
               '![Sweep](sweep.png)', '', '![Thermal control](thermal_control.png)', '',
               'These curves compare configured traffic proxies, not validated GPU architectures.',
               'Width sweep opens additional lanes subject to endpoint/routing caps; it does not optimize bank counts or placement.',
               'Constant-fill thermal invariance is a property of the homogenized model, not a proof that real pitch has no thermal effect.',
               'The workload temperature is the steady limit of continuous repeated work, not the peak of a single short kernel.', '',
               '## Next calibration steps', '',
               '- Replace illustrative energies, parasitics and interface thermal resistance with measured or extracted data.',
               '- Import cycle-level traffic and module power traces; test bank conflicts and dependency latency.',
               '- Validate a few module APR and FEM points before claiming an optimal pitch.', '']
    (args.out/'REPORT.md').write_text('\n'.join(summary), encoding='utf-8')
    print(f'{len(rows)} points / {len(valid)} feasible. Heat residual <= {error:.3g} W. Output: {args.out.resolve()}')


if __name__ == '__main__':
    main()
