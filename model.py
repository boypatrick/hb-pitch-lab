"""HB pitch exploration: analytical performance + linear 2-tier thermal network.

All technology parameters are inputs. No foundry/SoIC calibration is implied.
SI units internally, except explicitly named *_um, *_mm2 and *_gbps fields.
"""
from dataclasses import dataclass
import math
import numpy as np
from scipy.sparse import coo_matrix, diags
from scipy.sparse.linalg import spsolve


def positive(name, value, allow_zero=False):
    if not math.isfinite(value) or value < 0 or (not allow_zero and value == 0):
        raise ValueError(f"{name} must be finite and {'nonnegative' if allow_zero else 'positive'}")


def fraction(name, value):
    if not math.isfinite(value) or not 0 < value <= 1:
        raise ValueError(f"{name} must be in (0, 1]")


def hb_geometry(pitch_um, cfg, mode):
    """Signal allocation and thermal Cu fill are deliberately independent inputs."""
    positive('pitch_um', pitch_um)
    if mode == 'constant_fill':
        diameter = cfg['pad_to_pitch_ratio'] * pitch_um
    elif mode == 'constant_diameter':
        diameter = cfg['fixed_pad_diameter_um']
    else:
        raise ValueError('Unknown pad mode')
    positive('pad diameter', diameter)
    if diameter >= pitch_um:
        raise ValueError('Pad diameter must be less than pitch; invalid geometry, not a process DRC')
    fraction('signal_fraction', cfg['signal_fraction'])
    fraction('pattern_coverage_fraction', cfg['pattern_coverage_fraction'])
    positive('window_mm2', cfg['window_mm2'])
    # Geometric upper bound; routing capacity is applied separately in evaluate().
    sites = math.floor(cfg['window_mm2'] * 1e6 / pitch_um**2)
    signals = math.floor(sites * cfg['signal_fraction'])
    cu_fill = cfg['pattern_coverage_fraction'] * math.pi / 4 * (diameter / pitch_um)**2
    for key in ('cu_path_r_m2k_w', 'dielectric_path_r_m2k_w'):
        positive(key, cfg[key])
    r_interface = 1.0 / (cu_fill / cfg['cu_path_r_m2k_w']
                         + (1 - cu_fill) / cfg['dielectric_path_r_m2k_w'])
    # Optional calibrated lookup overrides only the thermal interface model.
    table = cfg.get('interface_r_lookup', {}).get(mode, {})
    if table:
        pairs = sorted((float(p), float(r)) for p, r in table.items())
        if not pairs[0][0] <= pitch_um <= pairs[-1][0]:
            raise ValueError('Thermal lookup does not cover requested pitch; no extrapolation')
        for _, r in pairs:
            positive('interface lookup R', r)
        r_interface = float(np.interp(pitch_um, *zip(*pairs)))
    return {'signal_capacity_per_tile': signals, 'pad_diameter_um': diameter,
            'cu_fill_fraction': cu_fill, 'interface_r_m2k_w': r_interface}


@dataclass
class ThermalNetwork:
    G: object
    capacity: np.ndarray
    boundary_g: np.ndarray
    ambient_c: float
    grid_n: int

    def steady(self, power):
        power = self._power(power)
        rise = spsolve(self.G, power)
        return rise + self.ambient_c

    def _power(self, power):
        power = np.asarray(power, dtype=float)
        if power.shape != self.capacity.shape or not np.isfinite(power).all() or (power < 0).any():
            raise ValueError('Power must be a finite nonnegative vector with one value per thermal node')
        return power

    def transient(self, power, duration_s, dt_s, initial_c=None):
        """Backward Euler, fixed properties/power; no leakage or DVFS feedback."""
        positive('duration_s', duration_s)
        positive('dt_s', dt_s)
        power = self._power(power)
        initial = np.full_like(self.capacity, self.ambient_c) if initial_c is None else np.asarray(initial_c, dtype=float)
        if initial.shape != self.capacity.shape or not np.isfinite(initial).all():
            raise ValueError('Invalid initial temperature')
        rise = initial - self.ambient_c
        times, values = [0.0], [initial.copy()]
        t = 0.0
        while t < duration_s:
            step = min(dt_s, duration_s - t)
            if step < duration_s * 1e-14:
                break
            cd = self.capacity / step
            rise = spsolve(self.G + diags(cd), power + cd * rise)
            t += step
            times.append(t)
            values.append(rise + self.ambient_c)
        return np.array(times), np.array(values)

    def residuals(self, temperature, power):
        rise = np.asarray(temperature) - self.ambient_c
        p = self._power(power)
        return {'nodal_residual_w': float(np.max(np.abs(self.G @ rise - p))),
                'heat_balance_error_w': float(abs(self.boundary_g @ rise - p.sum()))}


def build_thermal(cfg, interface_r_m2k_w):
    """Two equal square dies, cell-centred slabs; lateral edges adiabatic.

    Boundary R'' includes the path from the outer Si surface to a fixed-temperature
    reservoir (e.g. a calibrated effective TIM/cooler resistance). Silicon half-
    thickness resistances are explicit. HB is massless and spatially homogenized.
    """
    n = cfg['grid_n']
    if not isinstance(n, int) or n < 1:
        raise ValueError('grid_n must be a positive integer')
    for key in ('die_side_mm', 'silicon_k_w_mk', 'silicon_heat_capacity_j_m3k', 'top_boundary_r_m2k_w'):
        positive(key, cfg[key])
    if len(cfg['thickness_um']) != 2:
        raise ValueError('Exactly two die thicknesses required')
    for t in cfg['thickness_um']:
        positive('thickness_um', t)
    positive('interface_r_m2k_w', interface_r_m2k_w)
    positive('ambient_c', cfg['ambient_c'] + 273.15)
    if cfg.get('bottom_boundary_r_m2k_w') is not None:
        positive('bottom_boundary_r_m2k_w', cfg['bottom_boundary_r_m2k_w'])
    dx = cfg['die_side_mm'] * 1e-3 / n
    area = dx**2
    k = cfg['silicon_k_w_mk']
    thickness = np.asarray(cfg['thickness_um']) * 1e-6
    count = 2 * n * n
    rows, cols, data = [], [], []
    def add(i, j, val):
        rows.append(i); cols.append(j); data.append(val)
    def edge(i, j, g):
        add(i, i, g); add(j, j, g); add(i, j, -g); add(j, i, -g)
    for tier in range(2):
        for y in range(n):
            for x in range(n):
                i = tier*n*n + y*n+x
                if x + 1 < n:
                    edge(i, i+1, k*thickness[tier])
                if y + 1 < n:
                    edge(i, i+n, k*thickness[tier])
    gv = area / (thickness.sum()/(2*k) + interface_r_m2k_w)
    for i in range(n*n):
        edge(i, i+n*n, gv)
    boundary = np.zeros(count)
    boundary[:n*n] = area/(thickness[0]/(2*k) + cfg['top_boundary_r_m2k_w'])
    if cfg.get('bottom_boundary_r_m2k_w') is not None:
        boundary[n*n:] = area/(thickness[1]/(2*k) + cfg['bottom_boundary_r_m2k_w'])
    for i, g in enumerate(boundary):
        add(i, i, g)
    capacity = np.repeat(thickness*area*cfg['silicon_heat_capacity_j_m3k'], n*n)
    G = coo_matrix((data, (rows, cols)), shape=(count, count)).tocsr()
    return ThermalNetwork(G, capacity, boundary, cfg['ambient_c'], n)


def distribute_power(top_w, bottom_w, cfg):
    result = []
    for watts, field in zip((top_w, bottom_w), ('top_weights', 'bottom_weights')):
        positive('tier power', watts, allow_zero=True)
        weights = np.array(cfg.get(field, [1.0]*(cfg['grid_n']**2)), dtype=float)
        if weights.shape != (cfg['grid_n']**2,) or not np.isfinite(weights).all() or (weights < 0).any() or weights.sum() <= 0:
            raise ValueError(f'{field}: expected nonnegative weights with positive sum')
        result.extend(weights / weights.sum() * watts)
    return np.array(result)


def evaluate(config, architecture, pitch_um, pad_mode, link_mode):
    """Latency is an optimistic overlap bound, not a cycle-accurate simulation.

    fixed_width keeps implemented data width fixed and flags insufficient sites.
    width_sweep selects the widest allowed endpoint subject to bond/routing caps.
    Width sweep is not an automatic architecture mapper or floorplan optimizer.
    All HB traffic is aggregated over a shared read/write data budget.
    """
    hb = config['hb']
    geo = hb_geometry(pitch_um, hb, pad_mode)
    for key in ('tile_count', 'endpoint_max_bits_per_tile', 'routing_limit_bits_per_tile', 'fixed_bits_per_tile'):
        val = architecture[key]
        if not isinstance(val, int) or val < 1:
            raise ValueError(f'{key} must be a positive integer')
    for key in ('work_ops', 'peak_ops_s', 'hb_bytes', 'sram_gbps', 'noc_gbps'):
        positive(key, architecture[key])
    positive('external_bytes', architecture['external_bytes'], True)
    if architecture['external_bytes']:
        positive('external_gbps', architecture['external_gbps'])
    for key in ('compute_pj_op', 'memory_pj_hb_byte', 'background_top_w', 'background_bottom_w'):
        positive(key, architecture[key], True)
    for key in ('lane_rate_gbps', 'endpoint_pj_bit', 'wire_pj_bit', 'lane_clock_mw', 'lane_area_um2'):
        positive(key, hb[key], key != 'lane_rate_gbps')
    fraction('payload_efficiency', hb['payload_efficiency'])
    fraction('signal_fraction', hb['signal_fraction'])
    capacity = min(geo['signal_capacity_per_tile'], architecture['routing_limit_bits_per_tile'], architecture['endpoint_max_bits_per_tile'])
    if link_mode == 'fixed_width':
        lanes = architecture['fixed_bits_per_tile']
        feasible = lanes <= capacity
    elif link_mode == 'width_sweep':
        lanes, feasible = capacity, capacity > 0
    else:
        raise ValueError('Unknown link mode')
    row = dict(architecture=architecture['name'], pitch_um=pitch_um,
               pad_mode=pad_mode, link_mode=link_mode, feasible=bool(feasible),
               implemented_bits_per_tile=lanes, **geo)
    if not feasible:
        row['reason'] = 'Data width exceeds bond/endpoint/routing capacity'
        return row, None
    tiles = architecture['tile_count']
    bw = lanes*tiles*hb['lane_rate_gbps']*hb['payload_efficiency']/8
    components = {
        'compute': architecture['work_ops']/architecture['peak_ops_s'],
        'hb': architecture['hb_bytes']/(bw*1e9),
        'sram': architecture['hb_bytes']/(architecture['sram_gbps']*1e9),
        'noc': architecture['hb_bytes']/(architecture['noc_gbps']*1e9),
        'external': architecture['external_bytes']/(architecture['external_gbps']*1e9) if architecture['external_bytes'] else 0,
    }
    overlap_runtime = max(components.values())
    startup = architecture.get('startup_latency_s', 0.0)
    positive('startup_latency_s', startup, True)
    runtime = overlap_runtime + startup
    bottleneck = ','.join(k for k, value in components.items() if abs(value-overlap_runtime) < overlap_runtime*1e-9)
    # User-supplied energy values. No invented pitch->energy improvement.
    lookup = hb.get('link_energy_lookup_pj_bit', {})
    link_pj = hb['endpoint_pj_bit'] + hb['wire_pj_bit']
    if lookup:
        pairs = sorted((float(p), float(e)) for p, e in lookup.items())
        if not pairs[0][0] <= pitch_um <= pairs[-1][0]:
            raise ValueError('Energy lookup does not cover requested pitch')
        for _, e in pairs:
            positive('lookup energy', e, True)
        link_pj = float(np.interp(pitch_um, *zip(*pairs)))
    link_power = architecture['hb_bytes']*8*link_pj*1e-12/runtime
    clock_power = lanes*tiles*hb['lane_clock_mw']*1e-3
    compute_power = architecture['work_ops']*architecture['compute_pj_op']*1e-12/runtime
    memory_power = architecture['hb_bytes']*architecture['memory_pj_hb_byte']*1e-12/runtime
    top = architecture['background_top_w'] + compute_power + .5*(link_power+clock_power)
    bottom = architecture['background_bottom_w'] + memory_power + .5*(link_power+clock_power)
    network = build_thermal(config['thermal'], geo['interface_r_m2k_w'])
    power = distribute_power(top, bottom, config['thermal'])
    temps = network.steady(power)
    slot_area = lanes*tiles*pitch_um**2/(hb['signal_fraction']*1e6)
    endpoint_area = lanes*tiles*hb['lane_area_um2']/1e6
    row.update(hb_gbps=bw, latency_ms=runtime*1e3,
               bottleneck=bottleneck, throughput_tops=architecture['work_ops']/runtime/1e12,
               top_power_w=top, bottom_power_w=bottom, total_power_w=top+bottom,
               energy_mj=(top+bottom)*runtime*1e3,
               hb_site_budget_mm2=slot_area, endpoint_cell_area_mm2=endpoint_area,
               fixed_stack_footprint_mm2=config['thermal']['die_side_mm']**2,
               total_die_silicon_area_mm2=2*config['thermal']['die_side_mm']**2,
               steady_tmax_c=float(temps.max()),
               steady_top_tmax_c=float(temps[:network.grid_n**2].max()),
               steady_bottom_tmax_c=float(temps[network.grid_n**2:].max()),
               steady_gradient_c=float(temps.max()-temps.min()),
               **network.residuals(temps, power))
    # Area budgets overlap die footprint; do NOT add them to die area.
    return row, (network, power, temps)
