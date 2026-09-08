import copy
import json
from pathlib import Path
import tempfile
import unittest

from module_flow import derive, evaluate_design, export_point
from module_specs import ROOT, resources, validate_modules, variants


class ModuleFlowTests(unittest.TestCase):
    def setUp(self):
        self.source=json.loads((ROOT/'examples/modules.json').read_text())
        self.env=json.loads((ROOT/'examples/demo.json').read_text())

    def test_bound_sweep(self):
        points=list(variants(self.source))
        self.assertEqual(len(points),6)
        for d in points:
            m={m['name']:m for m in d['modules']}
            self.assertEqual(m['queue']['parameters']['WIDTH'],m['link']['parameters']['WIDTH'])

    def test_numerical_resource_contract(self):
        d=next(variants(self.source));cfg,a=derive(d,self.env)
        self.assertEqual(a['peak_ops_s'],16e9)  # 16 MAC * 2 ops * 250 MHz * 2 tiles
        self.assertEqual(a['sram_gbps'],16)  # 4 banks * 64 bits * 250 MHz * 2 / 8
        self.assertEqual(a['fixed_bits_per_tile'],64)
        self.assertEqual(a['startup_latency_s'],12e-9)
        byname={m['name']:m for m in d['modules']}
        self.assertEqual(resources(byname['scratch'])['memory_bits'],8192)
        self.assertEqual(resources(byname['link'])['state_bits'],130)

    def test_reject_bad_integer_and_clock(self):
        d=next(variants(self.source))
        for bad in (0,-1,True,1.5):
            q=copy.deepcopy(d);q['modules'][0]['parameters']['ROWS']=bad
            with self.assertRaises(ValueError):validate_modules(q)
        for bad in (True,float('nan'),float('inf'),0):
            q=copy.deepcopy(d);q['clock_hz']=bad
            with self.assertRaises(ValueError):validate_modules(q)

    def test_no_unimplemented_precision(self):
        d=next(variants(self.source));d['costs']['integer_data_width']=4
        with self.assertRaisesRegex(ValueError,'precision'):derive(d,self.env)
        d['modules'][0]['type']='fp8_tensor'
        with self.assertRaisesRegex(ValueError,'No RTL'):validate_modules(d)

    def test_no_silent_width_adaptation(self):
        d=next(variants(self.source));d['modules'][3]['parameters']['WIDTH']=63
        with self.assertRaisesRegex(ValueError,'widths'):validate_modules(d)

    def test_no_binding_cycle(self):
        self.source['bindings'].append({'source':'queue.WIDTH','target':'link.WIDTH'})
        self.source['modules'][4].pop('sweep')
        with self.assertRaisesRegex(ValueError,'Cyclic'):list(variants(self.source))

    def test_no_ready_cycle(self):
        d=next(variants(self.source));d['connections'].append({'source':'link','target':'queue'})
        with self.assertRaisesRegex(ValueError,'Cyclic'):validate_modules(d)

    def test_thermal_partition_is_explicit(self):
        d=next(variants(self.source));d['modules'][0]['tier']=1
        with self.assertRaisesRegex(ValueError,'tier 0'):derive(d,self.env)

    def test_depth_one_resources(self):
        self.assertEqual(resources({'type':'stream_fifo','parameters':{'WIDTH':8,'DEPTH':1}})['state_bits'],3)

    def test_evaluate_export_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);data=evaluate_design(ROOT/'examples/modules.json',path/'eval')
            self.assertEqual(len(data['points']),18)
            self.assertEqual(sum(p['metrics']['feasible'] for p in data['points']),16)
            p=data['points'][0];out=path/'rtl'
            manifest=export_point(path/'eval/evaluation.json',p['point_id'][:12],out)
            self.assertEqual(manifest['resolved_design'],p['resolved_design'])
            self.assertEqual(manifest['cross_tier_streams'][0]['payload_bits'],64)
            self.assertIn('.WIDTH(64)',(out/'rtl/link_wrapper.sv').read_text())
            self.assertIn('u_tile1',(out/'rtl/lab_system_top.sv').read_text())
            self.assertNotIn('queue_out_data',(out/'rtl/lab_tile_top.sv').read_text())
            with self.assertRaisesRegex(ValueError,'already exists'):
                export_point(path/'eval/evaluation.json',p['point_id'],out)

    def test_reject_infeasible_and_tampered_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);data=evaluate_design(ROOT/'examples/modules.json',path/'eval')
            f=path/'eval/evaluation.json'
            p=next(p for p in data['points'] if not p['metrics']['feasible'])
            with self.assertRaisesRegex(ValueError,'does not fit'):export_point(f,p['point_id'],path/'rtl')
            data['points'][0]['metrics']['energy_mj']+=1;f.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'record mismatch'):
                export_point(f,data['points'][0]['point_id'],path/'rtl')

    def test_reject_stale_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);data=evaluate_design(ROOT/'examples/modules.json',path/'eval')
            data['library_sha256']='stale';f=path/'eval/evaluation.json';f.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'reevaluate'):
                export_point(f,data['points'][0]['point_id'],path/'rtl')


if __name__=='__main__':unittest.main()
