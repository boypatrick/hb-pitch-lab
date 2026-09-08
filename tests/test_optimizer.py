import copy
import json
from pathlib import Path
import tempfile
import unittest

from module_flow import evaluate_design
from module_specs import ROOT, digest
from optimize import load_inputs, rank_candidates, read_json, replay, run_optimization, solve, validate_policy, verify_evaluation
from ppa_costs import ppa_metrics, validate_costs


class OptimizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.data=evaluate_design(ROOT/'examples/modules.json',Path(cls.temp.name)/'eval')
        cls.cost=read_json(ROOT/'examples/costs_synthetic.json')
        cls.policy=read_json(ROOT/'examples/optimization_ppa.json')

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def policy_for(self, objectives, selection='weighted_sum'):
        p=copy.deepcopy(self.policy);p['selection']=selection;p['tie_breakers']=[]
        p['objectives']=[{'metric':m,'direction':d,'weight':w,'scale':s} for m,d,w,s in objectives]
        return p

    def test_pareto_and_weighted_score_against_hand_solution(self):
        # A=(1,4), B=(2,2), C=(4,1) are nondominated; D=(3,3) is dominated by B.
        candidates=[{'point_id':name,'eligible':True,'metrics':{'area_mm2':a,'power_w':p}}
                    for name,a,p in [('A',1,4),('B',2,2),('C',4,1),('D',3,3)]]
        policy=self.policy_for([('area_mm2','min',1,1),('power_w','min',1,1)])
        pareto, ranked=rank_candidates(candidates,policy)
        self.assertEqual(pareto,['A','B','C']);self.assertEqual(ranked[0],'B')
        self.assertEqual(candidates[1]['score'],2)

    def test_lexicographic_and_maximize(self):
        candidates=[{'point_id':name,'eligible':True,'metrics':{'area_mm2':a,'throughput_tops':p}}
                    for name,a,p in [('A',1,4),('B',2,8),('C',1,3)]]
        policy=self.policy_for([('area_mm2','min',1,1),('throughput_tops','max',1,1)],'lexicographic')
        pareto,ranked=rank_candidates(candidates,policy)
        self.assertEqual(pareto,['A','B']);self.assertEqual(ranked[0],'A')
        policy=self.policy_for([('throughput_tops','max',1,1)])
        self.assertEqual(rank_candidates(candidates,policy)[1][0],'B')

    def test_duplicate_objective_and_nonfinite_inputs_rejected(self):
        for bad in (0,-1,True,float('nan'),float('inf')):
            policy=copy.deepcopy(self.policy);policy['objectives'][0]['weight']=bad
            with self.assertRaises(ValueError):validate_policy(policy)
        policy=copy.deepcopy(self.policy);policy['objectives'].append(policy['objectives'][0])
        with self.assertRaises(ValueError):validate_policy(policy)

    def test_unknown_constraint_is_not_silently_ignored(self):
        policy=copy.deepcopy(self.policy);policy['constraints']['temperature']={'max':85}
        with self.assertRaises(ValueError):validate_policy(policy)

    def test_full_grid_determinism_and_declared_pitch_tie_break(self):
        first=solve(self.data,self.policy,self.cost)
        second=solve(self.data,self.policy,self.cost)
        self.assertEqual(digest(first),digest(second))
        self.assertEqual(first['evaluated_unique_count'],18)
        self.assertEqual(first['eligible_count'],8)
        winner=next(c for c in first['candidates'] if c['point_id']==first['selected_point_id'])
        self.assertEqual(winner['metrics']['pitch_um'],8)
        self.assertAlmostEqual(winner['metrics']['latency_ms'],0.031262)

    def test_known_resource_area_and_power_equations(self):
        # Set area: 1 µm² per memory bit; each module adds 0.01 W per tile.
        cost=copy.deepcopy(self.cost)
        for entry in cost['modules'].values():
            entry['area_um2']={'base':0,'memory_bits':1,'state_bits':0,'macs_per_cycle':0}
            entry['extra_idle_w']={'base':0.01,'memory_bits':0,'state_bits':0,'macs_per_cycle':0}
        p=self.data['points'][0];m=ppa_metrics(p,self.data['environment'],cost)
        # 2 tiles * (8192 SRAM + 2048 RF + 256 FIFO) bits.
        self.assertAlmostEqual(m['area_mm2'],0.020992)
        self.assertAlmostEqual(m['power_w']-p['metrics']['total_power_w'],0.12)
        self.assertAlmostEqual(m['energy_mj'],m['power_w']*m['latency_ms'])
        self.assertEqual(m['sram_bytes_per_tile'],1024)
        self.assertEqual(m['rf_bytes_per_tile'],256)
        self.assertEqual(m['fifo_bytes_per_tile'],32)

    def test_constraint_boundary_is_inclusive(self):
        p=copy.deepcopy(self.policy);p['constraints']={'latency_ms':{'min':0.031262,'max':0.031262}}
        self.assertGreater(solve(self.data,p,self.cost)['eligible_count'],0)

    def test_missing_timing_and_impossible_constraints_fail_closed(self):
        policy=copy.deepcopy(self.policy);policy['constraints']['timing_wns_ns']={'min':0}
        result=solve(self.data,policy,self.cost)
        self.assertEqual(result['status'],'NO_FEASIBLE_SOLUTION')
        self.assertIsNone(result['selected_point_id'])
        policy['constraints']={'area_mm2':{'max':1e-12}}
        self.assertEqual(solve(self.data,policy,self.cost)['eligible_count'],0)

    def test_search_budget_is_not_implicit_sampling(self):
        policy=copy.deepcopy(self.policy);policy['max_candidates']=2
        with self.assertRaisesRegex(ValueError,'Narrow the grid'):solve(self.data,policy,self.cost)

    def test_missing_or_tampered_candidate_is_detected(self):
        for mode in ('missing','metrics','resource'):
            data=copy.deepcopy(self.data)
            if mode=='missing':data['points'].pop()
            elif mode=='metrics':data['points'][0]['metrics']['energy_mj']+=1
            else:data['points'][0]['module_resources']['tensor']['macs_per_cycle']+=1
            with self.assertRaisesRegex(ValueError,'coverage/content'):verify_evaluation(data)

    def point_table(self):
        table={k:copy.deepcopy(v) for k,v in self.cost.items() if k!='modules'}
        table.update(mode='point_table',quality='reported',provenance='UNIT TEST, not real reported measurements',entries=[])
        for p in self.data['points']:
            if p['metrics']['feasible']:
                table['entries'].append({'point_id':p['point_id'],'area_mm2':0.1,'latency_ms':0.02,
                    'top_power_w':1,'bottom_power_w':2,'timing_wns_ns':0.1,'source':'Unit-test fixture'})
        return table

    def test_point_table_units_and_thermal_recomputation(self):
        cost=self.point_table();validate_costs(cost)
        m=ppa_metrics(self.data['points'][0],self.data['environment'],cost)
        self.assertEqual(m['power_w'],3);self.assertEqual(m['energy_mj'],0.06)
        self.assertEqual(m['throughput_tops'],0.05)
        self.assertGreater(m['steady_tmax_c'],40)
        self.assertLess(m['heat_balance_error_w'],1e-8)

    def test_no_point_table_fallback_or_fake_reported_estimate(self):
        cost=self.point_table();cost['entries'].pop(0)
        with self.assertRaisesRegex(ValueError,'Missing point-table'):solve(self.data,self.policy,cost)
        cost=copy.deepcopy(self.cost);cost['quality']='reported'
        with self.assertRaisesRegex(ValueError,'cannot claim'):validate_costs(cost)

    def test_reported_ppa_requires_timing_constraint(self):
        policy=copy.deepcopy(self.policy);policy['quality_requirement']='reported_ppa'
        with self.assertRaises(ValueError):solve(self.data,policy,self.cost)
        cost=self.point_table()
        with self.assertRaises(ValueError):solve(self.data,policy,cost)
        policy['constraints']['timing_wns_ns']={'min':0}
        self.assertIsNotNone(solve(self.data,policy,cost)['selected_point_id'])

    def test_duplicate_json_keys_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.json';p.write_text('{"x":1,"x":2}')
            with self.assertRaisesRegex(ValueError,'Duplicate'):read_json(p)

    def test_export_and_replay_binding_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'run'
            result=run_optimization(ROOT/'examples/modules.json',ROOT/'examples/optimization_ppa.json',out)
            self.assertEqual(digest(result),digest(replay(out)))
            binding=read_json(out/'selected_rtl/optimization_binding.json')
            self.assertEqual(binding['point_id'],result['selected_point_id'])
            with self.assertRaisesRegex(ValueError,'Output exists'):
                run_optimization(ROOT/'examples/modules.json',ROOT/'examples/optimization_ppa.json',out)
            result['selected_point_id']='tampered';(out/'optimization.json').write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError,'replay mismatch'):replay(out)


if __name__=='__main__':unittest.main()
