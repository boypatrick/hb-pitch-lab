"""Action-count costs and a deliberately uncalibrated spatial thermal adapter."""
from collections import defaultdict
import math
import numpy as np

from mtia_model import Cluster
from ppa_costs import exact_keys, number

AREA={'mac_lane','pe_control','scratch_bit','shared_bit','me_control','transport_state_bit','transport_lane'}
IDLE={'pe_lane','scratch_bit','shared_bit','me_control','transport_state_bit','transport_lane'}
ACTIONS={'mac_ops','vector_ops','scratch_read_bytes','scratch_write_bytes','shared_read_bytes','shared_write_bytes','nmc_add_ops','hb_bits'}


def validate_costs(c):
    exact_keys(c,{'schema_version','quality','provenance','area_um2','idle_w','action_pj','thermal'})
    if type(c['schema_version']) is not int or c['schema_version']!=1 or c['quality'] not in ('synthetic','estimated'):
        raise ValueError('MTIA action adapter supports synthetic/estimated, not reported or signoff')
    if not isinstance(c['provenance'],str) or not c['provenance'].strip():raise ValueError('Cost provenance required')
    for key,fields in (('area_um2',AREA),('idle_w',IDLE),('action_pj',ACTIONS)):
        exact_keys(c[key],fields)
        for name,value in c[key].items():number(value,name)
    t=c['thermal'];exact_keys(t,{'quality','ambient_c','sink_g_w_k','vertical_g_w_k','lateral_g_w_k'})
    if t['quality'] not in ('synthetic','estimated'):raise ValueError('No calibrated thermal mode yet')
    number(t['ambient_c'],'ambient_c',minimum=-273.15,positive=True)
    for k in ('sink_g_w_k','vertical_g_w_k','lateral_g_w_k'):number(t[k],k,positive=True)
    return c


def resources(d,c):
    sim=Cluster(d,c);p=d['parameters']
    transport={};lanes={}
    for name,link in [('dma_hb',sim.dma)]+[(f'pe{j}.hb',link) for j in range(sim.n) for link in (sim.req[j],sim.rsp[j],sim.wb[j])]:
        # Declared TX+RX padded registers, two integer counters, two state bits.
        bits=2*math.ceil(link.width/link.bits)*link.bits+66 if link.cut else 0
        transport[name]=transport.get(name,0)+bits
        lanes[name]=lanes.get(name,0)+(link.bits if link.cut else 0)
    return {'mac_lanes':p['pes']*p['lanes'],'scratch_bits':p['pes']*p['lanes']*8*p['scratch_rows'],
            'shared_bits':p['shared_entries']*32,'transport_state_bits':transport,'transport_lanes':lanes,
            'memory_contract':'per-lane scratch 2R1W, shared 1R1W with occupied-bit barrier'}


def costs(d,c,result,cost):
    p=d['parameters'];n=p['pes'];r=resources(d,c);a=cost['area_um2'];idle=cost['idle_w'];f=d['clock_hz']
    area=(r['mac_lanes']*a['mac_lane']+n*a['pe_control']+r['scratch_bits']*a['scratch_bit']+
          r['shared_bits']*a['shared_bit']+a['me_control']+sum(r['transport_state_bits'].values())*a['transport_state_bit']+
          sum(r['transport_lanes'].values())*a['transport_lane'])*1e-6
    base={f'pe{j}.compute':p['lanes']*idle['pe_lane'] for j in range(n)}
    base.update({f'pe{j}.scratch':p['lanes']*8*p['scratch_rows']*idle['scratch_bit'] for j in range(n)})
    base['me_nmc']=idle['me_control']+r['shared_bits']*idle['shared_bit']
    base.update({unit:bits*idle['transport_state_bit']+r['transport_lanes'][unit]*idle['transport_lane']
                 for unit,bits in r['transport_state_bits'].items()})
    energy=defaultdict(float);bins=defaultdict(lambda:defaultdict(float))
    for event in result['events']:
        e=event['count']*cost['action_pj'][event['action']]*1e-12
        energy[event['unit']]+=e;bins[event['cycle']//d['trace_bin_cycles']][event['unit']]+=e
    duration=result['cycles']/f
    powers={unit:watts+energy[unit]/duration for unit,watts in base.items()}
    trace=[]
    for b in range(math.ceil(result['cycles']/d['trace_bin_cycles'])):
        start=b*d['trace_bin_cycles'];end=min(result['cycles'],start+d['trace_bin_cycles']);dt=(end-start)/f
        trace.append({'start_cycle':start,'end_cycle':end,'module_power_w':{unit:watts+bins[b][unit]/dt for unit,watts in base.items()}})
    thermal=thermal_network(c,powers,n,cost['thermal'])
    power=sum(powers.values());energy_j=power*duration
    trace_energy=sum(sum(row['module_power_w'].values())*(row['end_cycle']-row['start_cycle'])/f for row in trace)
    if not math.isclose(trace_energy,energy_j,rel_tol=1e-11,abs_tol=1e-18):raise ValueError('Trace energy balance error')
    metrics={'area_mm2':area,'power_w':power,'latency_ms':duration*1e3,'energy_mj':energy_j*1e3,
             'throughput_tops':result['useful_ops']/duration/1e12,'steady_tmax_c':thermal['steady_tmax_c'],
             'top_power_w':thermal['top_power_w'],'bottom_power_w':thermal['bottom_power_w'],
             'pitch_um':c['pitch_um'],'timing_wns_ns':None,
             'sram_bytes_per_tile':p['lanes']*p['scratch_rows'], 'rf_bytes_per_tile':0,'fifo_bytes_per_tile':0,
             'hb_site_budget_mm2':0 if c['partition']=='2d' else c['required_sites']*c['pitch_um']**2/d['physical']['signal_fraction']*1e-6*(n if c['partition']=='local_scratch' else 1),
             'nodal_residual_w':thermal['nodal_residual_w'],'heat_balance_error_w':thermal['heat_balance_error_w']}
    return {'metrics':metrics,'resources':r,'module_mean_power_w':powers,'power_trace':trace,'thermal':thermal,
            'power_scope':'PE/scratch/ME/NMC/digital transports only. External HBM/NIC/package power excluded.',
            'cost_quality':cost['quality'],'thermal_quality':cost['thermal']['quality']}


def thermal_network(c,powers,n,t):
    """One lateral row of cells per tier, including a dedicated ME/NMC cell.

    Conductances are fixed synthetic inputs, not extracted from pitch. 2D uses
    one layer and zero-latency direct wires. Cell averages are not local junction
    hot spots. No HBM/package/BEOL/FEM calibration or transient solver is implied.
    """
    cells=n+1;tiers=1 if c['partition']=='2d' else 2;size=cells*tiers
    G=np.zeros((size,size));boundary=np.zeros(size);power=np.zeros(size)
    def edge(i,j,g):G[i,i]+=g;G[j,j]+=g;G[i,j]-=g;G[j,i]-=g
    for tier in range(tiers):
        for j in range(cells-1):edge(tier*cells+j,tier*cells+j+1,t['lateral_g_w_k'])
    for j in range(cells):
        boundary[j]=t['sink_g_w_k'];G[j,j]+=boundary[j]
        if tiers==2:edge(j,cells+j,t['vertical_g_w_k'])
    positions={}
    for unit,watts in powers.items():
        if unit.startswith('pe'):
            index=int(unit.split('.')[0][2:]);kind=unit.split('.')[1]
            tier=1 if tiers==2 and kind=='scratch' and c['partition']=='local_scratch' else 0
        else:index=n;tier=tiers-1
        if unit.endswith('.hb') or unit=='dma_hb':
            # Endpoints' digital transport activity split equally across tier faces.
            for layer in range(tiers):power[layer*cells+index]+=watts/tiers
            positions[unit]={'x_cell':index,'tier':'boundary' if tiers==2 else 0}
        else:
            power[tier*cells+index]+=watts;positions[unit]={'x_cell':index,'tier':tier}
    rise=np.linalg.solve(G,power);residual=G@rise-power
    return {'steady_tmax_c':float(t['ambient_c']+rise.max()),'cell_temperature_c':(rise+t['ambient_c']).tolist(),
            'cell_power_w':power.tolist(),'module_positions':positions,
            'top_power_w':float(power[:cells].sum()),'bottom_power_w':float(power[cells:].sum()),
            'nodal_residual_w':float(np.max(np.abs(residual))),
            'heat_balance_error_w':float(abs(boundary@rise-power.sum())),
            'scope':'Synthetic steady cell-average model with fixed conductances, not package/junction signoff'}
