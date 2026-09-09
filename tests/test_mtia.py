import copy
import json
from pathlib import Path
import tempfile
import unittest

from module_specs import ROOT,digest
from optimize import read_json
from mtia_model import (Cluster, Link, candidates, compile_workload, encode_command,
                        io_contract, pack, signed, simulate, validate_design)
from mtia_costs import costs,validate_costs
from mtia_flow import evaluate,save_search,replay_search,verify
from mtia_rtl import compile_rtl,replay_stimulus,export


def demo():return read_json(ROOT/'examples/mtia.json')


def small(pes=1,lanes=2):
    d=demo();d['parameters'].update(pes=pes,lanes=lanes,scratch_rows=16,shared_entries=16)
    d['physical'].update(local_widths_bits=[8,lanes*16],coarse_bits=24)
    for w in d['workloads']:
        w.update(outputs_per_pe=2,vectors_per_output=2,phases=2,hbm_gap_cycles=3,nic_gap_cycles=7)
    return validate_design(d)


class MtiaModelTests(unittest.TestCase):
    def test_geometry_accounts_for_all_payload_directions(self):
        cs=list(candidates(validate_design(demo())))
        self.assertEqual(len(cs),13);self.assertEqual(sum(c['geometric_feasible'] for c in cs),10)
        self.assertEqual([(c['pitch_um'],c['sites']) for c in cs if c['partition']=='local_scratch' and c['hb_bits']==128],[(8,32),(4,128),(2,512)])
        self.assertFalse(next(c for c in cs if c['partition']=='local_scratch' and c['pitch_um']==4 and c['hb_bits']==128)['geometric_feasible'])

    def test_useful_kernel_and_counterexamples(self):
        d=demo();cs=list(candidates(d))
        coarse=next(c for c in cs if c['partition']=='coarse')
        narrow=next(c for c in cs if c['partition']=='local_scratch' and c['hb_bits']==16)
        wide=next(c for c in cs if c['partition']=='local_scratch' and c['hb_bits']==128 and c['geometric_feasible'])
        measured={}
        for w in d['workloads'][:3]:
            a=simulate(d,narrow,w);b=simulate(d,wide,w)
            self.assertEqual([x['value'] for x in a['outputs']],[x['value'] for x in b['outputs']])
            self.assertEqual(a['useful_ops'],b['useful_ops'])
            measured[w['name']]=1-b['cycles']/a['cycles']
        self.assertGreater(measured['local_supply'],0.25)
        self.assertLess(measured['hbm_limited'],0.02)
        self.assertEqual(measured['nic_limited'],0)
        c2=dict(coarse,pitch_um=2)
        self.assertEqual(simulate(d,coarse,d['workloads'][0])['cycles'],simulate(d,c2,d['workloads'][0])['cycles'])

    def test_fixed_width_is_a_true_control(self):
        d=small();cs=[c for c in candidates(d) if c['partition']=='local_scratch' and c['hb_bits']==8]
        outputs=[simulate(d,c,d['workloads'][0]) for c in cs]
        self.assertEqual(len({digest(x) for x in outputs}),1)

    def test_serializer_roundtrip_and_backpressure(self):
        for width,bits,stages in [(1,8,0),(38,8,1),(71,24,3),(128,64,0)]:
            link=Link(width,bits,stages,True);value=(1<<width)-1
            self.assertTrue(link.ready(False));link.tick(True,value,False)
            clocks=0;traffic=0
            while not link.forward(False,0)[0]:
                traffic+=link.tick(False,0,False);clocks+=1
            self.assertEqual(clocks,(width+bits-1)//bits+stages)
            self.assertEqual(traffic,((width+bits-1)//bits)*bits)
            for _ in range(5):
                self.assertEqual(link.forward(False,0),(True,value));self.assertFalse(link.ready(True));link.tick(False,0,False)
            link.tick(False,0,True);self.assertTrue(link.ready(False))

    def test_int8_signed_and_int32_wrap_with_hand_calculation(self):
        d=small();c=next(candidates(d));s=Cluster(d,c)
        fields,_=io_contract(d['parameters'])
        def tick(**kw):
            i={k:0 for k,_ in fields};i.update(out_ready=1);i.update(kw);return s.tick(i)[0]
        tick(load_valid=1,load_addr=0,load_data=pack([(-128,8),(127,8)]))
        tick(load_valid=1,load_addr=1,load_data=pack([(-128,8),(-1,8)]))
        command={'op':'dot','a':0,'b':1,'sa':0,'sb':0,'vectors':1,'dst':0}
        tick(cmd_valid=1,cmd_data=encode_command(d['parameters'],command),me_valid=1,me_count=1)
        seen=[];answer=None
        for _ in range(30):
            o=tick(nic_valid=1,nic_data=0x7fffffff)
            if o['wb_valid'] and o['wb_ready']:seen.append(signed(o['wb_data']))
            if o['out_valid']:answer=signed(o['out_data']);break
        self.assertEqual(seen,[16257]) # 16384 - 127
        self.assertEqual(answer,-2147467392) # wrap(2147483647 + 16257)

    def test_memory_side_engine_waits_for_valid_local_result(self):
        d=small();s=Cluster(d,next(candidates(d)));fields,_=io_contract(d['parameters'])
        i={k:0 for k,_ in fields};i.update(me_valid=1,me_count=1,nic_valid=1,nic_data=9,out_ready=1)
        s.tick(i);i['me_valid']=0
        for _ in range(20):
            o,_,stall=s.tick(i)
            self.assertFalse(o['nic_ready']);self.assertFalse(o['out_valid']);self.assertEqual(stall['local_result_wait'],1)

    def test_invalid_inputs_fail_closed(self):
        for mutate in [lambda d:d['parameters'].update(pes=True),lambda d:d['parameters'].update(scratch_rows=15),
                       lambda d:d.update(architecture='fp8'),lambda d:d['physical'].update(signal_fraction=1.1),
                       lambda d:d['physical'].update(pitches_um=[float('nan')]),
                       lambda d:d['workloads'][0].update(output_stall_period=1),
                       lambda d:d['workloads'][0].update(vectors_per_output=32),
                       lambda d:d['workloads'][0].update(kernel='cuda')]:
            with self.subTest(mutate=mutate):
                d=demo();mutate(d)
                with self.assertRaises((ValueError,TypeError)):validate_design(d)
        d=small()
        with self.assertRaises(ValueError):encode_command(d['parameters'],{'op':'dot','a':15,'b':0,'sa':1,'sb':0,'vectors':2,'dst':0})

    def test_cycle_budget_is_not_success(self):
        d=small();d['max_cycles']=1
        with self.assertRaises(RuntimeError):simulate(d,next(candidates(d)),d['workloads'][0])

    def test_power_trace_energy_and_spatial_conservation(self):
        d=small();cost=validate_costs(read_json(ROOT/'examples/mtia_costs_synthetic.json'))
        for c in [x for x in candidates(d) if x['geometric_feasible']]:
            result=simulate(d,c,d['workloads'][0]);a=costs(d,c,result,cost);m=a['metrics']
            self.assertAlmostEqual(m['energy_mj'],m['power_w']*m['latency_ms'],places=15)
            self.assertAlmostEqual(m['top_power_w']+m['bottom_power_w'],m['power_w'],places=14)
            self.assertLess(m['nodal_residual_w'],1e-12)
            if c['partition']=='2d':self.assertEqual(m['bottom_power_w'],0)
            expected_tier=1 if c['partition']=='local_scratch' else 0
            self.assertEqual(a['thermal']['module_positions']['pe0.scratch']['tier'],expected_tier)

    def test_model_sram_content_matches_scalar_gemm_oracle(self):
        d=small(pes=3,lanes=4);w=d['workloads'][0]
        phase=compile_workload(d['parameters'],w)[0]
        import numpy as np
        for pe,cmds in enumerate(phase['commands']):
            mem={x['addr']:x['data'] for x in phase['loads'] if x['pe']==pe}
            def row(addr):return [signed((mem[addr]>>(8*j))&255,8) for j in range(4)]
            for cmd in cmds:
                aa=np.array([row(cmd['a']+k) for k in range(cmd['vectors'])],dtype=np.int64).flatten()
                bb=np.array([row(cmd['b']+k) for k in range(cmd['vectors'])],dtype=np.int64).flatten()
                self.assertEqual(int(aa@bb),phase['oracle'][cmd['dst']])

    def test_link_width_has_area_cost_and_engines_overlap(self):
        d=demo();cost=validate_costs(read_json(ROOT/'examples/mtia_costs_synthetic.json'))
        points=[c for c in candidates(d) if c['partition']=='local_scratch' and c['pitch_um']==2]
        areas=[]
        for c in points:
            result=simulate(d,c,d['workloads'][0])
            areas.append(costs(d,c,result,cost)['metrics']['area_mm2'])
            self.assertGreater(result['counts']['pe_me_concurrent_busy_cycles'],0)
        self.assertTrue(all(a<b for a,b in zip(areas,areas[1:])))


class MtiaFlowTests(unittest.TestCase):
    def inputs(self):
        d=small();d['workloads']=d['workloads'][:1];d['physical']['pitches_um']=[8,2]
        return d,read_json(ROOT/'examples/mtia_policy.json'),read_json(ROOT/'examples/mtia_costs_synthetic.json')

    def test_optimizer_replay_and_tamper_detection(self):
        d,p,c=self.inputs();e,details=evaluate(d,p,c)
        self.assertIn(e['selected_point_id'],e['pareto_ids'])
        with tempfile.TemporaryDirectory() as tmp:
            save_search(Path(tmp),e,details);replay_search(tmp)
            path=Path(tmp)/'evaluation.json';changed=copy.deepcopy(e);changed['candidates'][0]['metrics']['power_w']+=1
            path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):replay_search(tmp)

    def test_no_fake_sta_or_infeasible_selection(self):
        d,p,c=self.inputs();p['constraints']['timing_wns_ns']={'min':0}
        e,_=evaluate(d,p,c);self.assertIsNone(e['selected_point_id']);self.assertEqual(e['eligible_count'],0)
        p['quality_requirement']='reported_ppa'
        with self.assertRaises(ValueError):evaluate(d,p,c)

    def test_failed_run_cannot_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'run.json').write_text(json.dumps({'format':'mtia-qc-v1','status':'FAIL'}))
            with self.assertRaises(ValueError):verify(tmp)

    def test_unknown_cost_keys_and_nonfinite_values_rejected(self):
        _,_,c=self.inputs();c['action_pj']['hb_bits']=float('inf')
        with self.assertRaises(ValueError):validate_costs(c)

    def test_export_rejects_unregistered_or_infeasible_candidate(self):
        d=demo();cs=list(candidates(d))
        for c in [dict(cs[0],hb_bits=999),next(c for c in cs if not c['geometric_feasible'])]:
            with tempfile.TemporaryDirectory() as tmp:
                out=Path(tmp)/'export'
                with self.assertRaises(ValueError):export(d,c,'invalid',out,'test')
                self.assertFalse(out.exists())
        _,_,c=self.inputs();c['quality']='reported'
        with self.assertRaises(ValueError):validate_costs(c)


class MtiaRtlTests(unittest.TestCase):
    def test_stalled_writeback_is_locked_when_new_source_arrives(self):
        # Occupy slot 0, stall PE1 on it, then let higher-priority PE0 arrive.
        # Only real commands/DMA are used: no hierarchical state injection.
        d=small(pes=2);cs=list(candidates(d))
        selected=[cs[0],next(c for c in cs if c['partition']=='coarse'),
                  next(c for c in cs if c['partition']=='local_scratch' and c['geometric_feasible'])]
        for c in selected:
            with self.subTest(cut=c['partition']),tempfile.TemporaryDirectory() as tmp:
                sim=Cluster(d,c);ins,outs=io_contract(d['parameters']);stim=[];accepted=[]
                def tick(**kw):
                    inp={k:0 for k,_ in ins};inp.update(out_ready=1);inp.update(kw)
                    out,_,_=sim.tick(inp)
                    mask=pack([((1<<w)-1 if k not in ('out_data','wb_data') or out['out_valid' if k=='out_data' else 'wb_valid'] else 0,w) for k,w in outs])
                    stim.append((pack([(inp[k],w) for k,w in ins]),pack([(out[k],w) for k,w in outs]),mask))
                    if out['wb_valid'] and out['wb_ready']:accepted.append((out['wb_data']>>32,signed(out['wb_data'])))
                    return out
                def until(predicate,**kw):
                    for _ in range(300):
                        out=tick(**kw)
                        if predicate(out):return out
                    self.fail('Directed protocol test timed out')
                for pe in range(2):
                    for row,value in [(0,1),(1,2)]:
                        until(lambda o:o['load_ready'],load_valid=1,load_pe=pe,load_addr=row,load_data=pack([(value,8)]*2))
                while sim.dma.state:tick()
                def command(pe,dst):
                    word=encode_command(d['parameters'],dict(op='dot',a=0,b=1,sa=0,sb=0,vectors=1,dst=dst))
                    until(lambda o:(o['cmd_ready']>>pe)&1,cmd_valid=1<<pe,cmd_data=word<<(sim.cw*pe))
                command(1,0);until(lambda o:o['wb_valid'] and o['wb_ready'])
                command(1,0);held=until(lambda o:o['wb_valid'] and not o['wb_ready'])['wb_data']
                command(0,1)
                for _ in range(80):
                    o=tick();self.assertTrue(o['wb_valid']);self.assertFalse(o['wb_ready']);self.assertEqual(o['wb_data'],held)
                until(lambda o:o['me_ready'],me_valid=1,me_count=2)
                answer=until(lambda o:o['out_valid'],nic_valid=1,nic_data=0)
                self.assertEqual(signed(answer['out_data']),8)
                self.assertEqual(accepted,[(0,4),(0,4),(1,4)])
                image=compile_rtl(d,c,tmp)
                self.assertEqual(replay_stimulus(image,stim,Path(tmp)/'locked')['cycles'],len(stim))

    def test_varied_parameters_and_kernels_match_rtl_cycles(self):
        # The release runner additionally replays EVERY feasible example candidate.
        for pes,lanes,stages in [(1,1,0),(3,4,2)]:
            d=small(pes,lanes);d['physical']['link_stages']=stages
            cs=list(candidates(d));selected=[cs[0],next(c for c in cs if c['partition']=='coarse'),
                next(c for c in cs if c['partition']=='local_scratch' and c['geometric_feasible'])]
            for candidate in selected:
                with self.subTest(pes=pes,lanes=lanes,stages=stages,cut=candidate['partition']),tempfile.TemporaryDirectory() as tmp:
                    image=compile_rtl(d,candidate,tmp)
                    for w in (d['workloads'][0],d['workloads'][3],d['workloads'][4]):
                        result,stim=simulate(d,candidate,w,True)
                        report=replay_stimulus(image,stim,Path(tmp)/w['name'])
                        self.assertEqual(report['cycles'],result['cycles'])


if __name__=='__main__':unittest.main()
