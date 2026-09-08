import copy
import json
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import build_thermal, distribute_power, evaluate, hb_geometry

BASE = Path(__file__).resolve().parents[1]


class PhysicsTests(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((BASE/'examples/demo.json').read_text())

    def test_single_column_matches_series_resistances(self):
        cfg = self.cfg['thermal']; cfg['grid_n'] = 1
        ri = 1e-6
        net = build_thermal(cfg, ri)
        area = (cfg['die_side_mm']*1e-3)**2
        tu, tl = np.array(cfg['thickness_um'])*1e-6
        k = cfg['silicon_k_w_mk']
        rs = (cfg['top_boundary_r_m2k_w']+tu/(2*k))/area
        rv = ((tu+tl)/(2*k)+ri)/area
        actual = net.steady([80,20])
        expected = [cfg['ambient_c']+100*rs, cfg['ambient_c']+100*rs+20*rv]
        np.testing.assert_allclose(actual, expected, rtol=1e-12)

    def test_heat_conservation_nonuniform(self):
        net = build_thermal(self.cfg['thermal'], 1e-6)
        p = distribute_power(80, 20, self.cfg['thermal'])
        checks = net.residuals(net.steady(p), p)
        self.assertLess(max(checks.values()), 1e-8)

    def test_zero_power_is_ambient(self):
        net = build_thermal(self.cfg['thermal'], 1e-6)
        np.testing.assert_allclose(net.steady(np.zeros(32)), 40)

    def test_uniform_load_grid_refinement_invariant(self):
        values = []
        for n in (1, 2, 4, 8):
            cfg = copy.deepcopy(self.cfg['thermal']); cfg['grid_n'] = n
            cfg.pop('top_weights'); cfg.pop('bottom_weights')
            net = build_thermal(cfg, 1e-6)
            values.append(net.steady(distribute_power(80,20,cfg)).max())
        np.testing.assert_allclose(values, values[0], atol=1e-9)

    def test_transient_converges_to_steady_and_conserves_energy(self):
        net = build_thermal(self.cfg['thermal'], 1e-6)
        p = distribute_power(80,20,self.cfg['thermal'])
        times, values = net.transient(p,.2,.001)
        self.assertTrue((np.diff(values, axis=0) >= -1e-9).all())
        np.testing.assert_allclose(values[-1],net.steady(p),atol=1e-6)
        for i in (1,5,20):
            dt = times[i]-times[i-1]
            storage = net.capacity@(values[i]-values[i-1])/dt
            outflow = net.boundary_g@(values[i]-net.ambient_c)
            self.assertAlmostEqual(storage+outflow,p.sum(),places=7)

    def test_same_cu_fraction_preserves_homogenized_interface(self):
        vals = [hb_geometry(p,self.cfg['hb'],'constant_fill') for p in (8,4,2,1)]
        np.testing.assert_allclose([v['cu_fill_fraction'] for v in vals], np.pi/16)
        np.testing.assert_allclose([v['interface_r_m2k_w'] for v in vals],vals[0]['interface_r_m2k_w'])

    def test_constant_diameter_increases_fill_and_conductance(self):
        a = hb_geometry(4,self.cfg['hb'],'constant_diameter')
        b = hb_geometry(2,self.cfg['hb'],'constant_diameter')
        self.assertAlmostEqual(b['cu_fill_fraction']/a['cu_fill_fraction'],4)
        self.assertLess(b['interface_r_m2k_w'],a['interface_r_m2k_w'])

    def test_invalid_pad_geometry_and_nan_rejected(self):
        for pitch in (.4,float('nan')):
            with self.assertRaises(ValueError):
                hb_geometry(pitch,self.cfg['hb'],'constant_diameter')

    def test_fixed_width_infeasibility_not_silent_serialization(self):
        row,_ = evaluate(self.cfg,self.cfg['architectures'][1],8,'constant_fill','fixed_width')
        self.assertFalse(row['feasible'])
        self.assertNotIn('latency_ms',row)

    def test_bandwidth_saturates_and_lanes_cap(self):
        arch = self.cfg['architectures'][1]
        rows = [evaluate(self.cfg,arch,p,'constant_fill','width_sweep')[0] for p in (8,4,2,1)]
        self.assertGreater(rows[0]['latency_ms'],rows[1]['latency_ms'])
        self.assertGreater(rows[1]['latency_ms'],rows[2]['latency_ms'])
        self.assertAlmostEqual(rows[2]['latency_ms'],rows[3]['latency_ms'])
        self.assertLessEqual(rows[3]['implemented_bits_per_tile'],arch['routing_limit_bits_per_tile'])

    def test_pitch_alone_does_not_improve_fixed_width_performance(self):
        arch = self.cfg['architectures'][0]
        a = evaluate(self.cfg,arch,4,'constant_fill','fixed_width')[0]
        b = evaluate(self.cfg,arch,1,'constant_fill','fixed_width')[0]
        for key in ('latency_ms','energy_mj','steady_tmax_c'):
            self.assertAlmostEqual(a[key],b[key])
        self.assertGreater(a['hb_site_budget_mm2'],b['hb_site_budget_mm2'])

    def test_calibration_lookup_and_no_extrapolation(self):
        hb = self.cfg['hb']
        hb['interface_r_lookup']={'constant_fill':{'1':1e-6,'4':4e-6}}
        self.assertAlmostEqual(hb_geometry(2,hb,'constant_fill')['interface_r_m2k_w'],2e-6)
        with self.assertRaises(ValueError):
            hb_geometry(8,hb,'constant_fill')

    def test_additional_cooling_reduces_peak(self):
        cfg = self.cfg['thermal']
        power = distribute_power(80,20,cfg)
        a = build_thermal(cfg,1e-6).steady(power)
        cfg['bottom_boundary_r_m2k_w']=cfg['top_boundary_r_m2k_w']
        b = build_thermal(cfg,1e-6).steady(power)
        self.assertLess(b.max(),a.max())


if __name__ == '__main__':
    unittest.main()
