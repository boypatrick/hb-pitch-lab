"""Executable descriptor PE/scratch/collective model, clocked like rtl/mtia_*.sv.

The independent scalar oracle checks useful work; RTL replay checks cycle timing.
This intentionally bounded INT8/INT32 subsystem has no vendor ISA/FP semantics.
"""
from collections import Counter
from dataclasses import dataclass
import math
import random
import re

from module_specs import integer
from ppa_costs import exact_keys, number

PARTITIONS = {'2d': 0, 'coarse': 1, 'local_scratch': 2}
OPS = {'dot': 0, 'add_sum': 1, 'relu_sum': 2}
PARAMETERS = {'pes': (1, 4), 'lanes': (1, 16), 'scratch_rows': (8, 256), 'shared_entries': (8, 256)}


def bits_for(n):
    return max(1, (n-1).bit_length())


def signed(n, width=32):
    n &= (1 << width)-1
    return n-(1 << width) if n & (1 << (width-1)) else n


def pack(values):
    """Low-to-high (value, width) fields, also used by the documented SV ports."""
    result = offset = 0
    for value, width in values:
        result |= (int(value) & ((1 << width)-1)) << offset
        offset += width
    return result


def unpack(value, widths):
    result = []
    for width in widths:
        result.append(value & ((1 << width)-1)); value >>= width
    return result


def validate_design(d):
    exact_keys(d, {'schema_version', 'architecture', 'provenance', 'parameters', 'clock_hz',
                   'physical', 'workloads', 'max_cycles', 'trace_bin_cycles'})
    if type(d['schema_version']) is not int or d['schema_version'] != 1 or d['architecture'] != 'mtia-like-int8-v1':
        raise ValueError('Only mtia-like-int8-v1 is implemented; no FP or RISC-V substitution')
    if not isinstance(d['provenance'], str) or not d['provenance'].strip():
        raise ValueError('Design provenance required')
    exact_keys(d['parameters'], set(PARAMETERS))
    for key, (lo, hi) in PARAMETERS.items():
        integer(d['parameters'][key], lo, hi, key)
    for key in ('scratch_rows', 'shared_entries'):
        n = d['parameters'][key]
        if n & (n-1): raise ValueError(key+' must be a power of two')
    number(d['clock_hz'], 'clock_hz', positive=True)
    if d['clock_hz'] > 1e10: raise ValueError('clock_hz exceeds model range')
    integer(d['max_cycles'], 100, 1000000, 'max_cycles')
    integer(d['trace_bin_cycles'], 1, 100000, 'trace_bin_cycles')
    p = d['physical']
    exact_keys(p, {'pitches_um', 'local_window_um2', 'coarse_window_um2', 'signal_fraction',
                   'local_widths_bits', 'coarse_bits', 'link_stages'})
    for key in ('local_window_um2', 'coarse_window_um2', 'signal_fraction'):
        number(p[key], key, positive=True)
    if p['signal_fraction'] > 1: raise ValueError('signal_fraction must be <= 1')
    integer(p['coarse_bits'], 8, 256, 'coarse_bits')
    integer(p['link_stages'], 0, 8, 'link_stages')
    for key in ('pitches_um', 'local_widths_bits'):
        if not isinstance(p[key], list) or not p[key] or len(p[key]) > 16:
            raise ValueError('Nonempty bounded search axis required: '+key)
        for v in p[key]:
            if key == 'pitches_um': number(v, key, positive=True)
            else:
                integer(v, 8, d['parameters']['lanes']*16, key)
                if v % 8: raise ValueError('HB payload widths must be byte multiples')
        if len(set(p[key])) != len(p[key]): raise ValueError('Duplicate search value')
    if not isinstance(d['workloads'], list) or not 1 <= len(d['workloads']) <= 16:
        raise ValueError('Need 1..16 workloads')
    names = set()
    for w in d['workloads']:
        exact_keys(w, {'name', 'kernel', 'outputs_per_pe', 'vectors_per_output', 'phases', 'seed',
                       'hbm_gap_cycles', 'nic_gap_cycles', 'output_stall_period'})
        if not isinstance(w['name'], str) or not re.fullmatch('[a-z][a-z0-9_]*', w['name']) or w['name'] in names:
            raise ValueError('Workload names must be unique simple identifiers')
        names.add(w['name'])
        if w['kernel'] not in ('gemm', 'embedding', 'vector'): raise ValueError('Unsupported kernel')
        for key,lo,hi in [('outputs_per_pe',1,16),('vectors_per_output',1,32),('phases',1,8),
                          ('seed',0,2**31-1),('hbm_gap_cycles',1,4096),('nic_gap_cycles',1,4096),
                          ('output_stall_period',0,64)]: integer(w[key],lo,hi,key)
        if w['output_stall_period'] == 1: raise ValueError('Output period 1 never accepts results')
        if w['outputs_per_pe']*d['parameters']['pes'] > d['parameters']['shared_entries']:
            raise ValueError('Collective output set exceeds shared entries')
        # Compile now so infeasible mappings fail before search or RTL export.
        compile_workload(d['parameters'], w)
    return d


def candidates(d):
    """Geometry counts dedicated request, operand-response and result lanes.

    Signal fraction reserves P/G, clock, reset, handshake/control and routing.
    Coarse global window covers DMA plus all per-PE result interfaces together.
    """
    p, n = d['physical'], d['parameters']['pes']
    yield {'partition': '2d', 'pitch_um': 0, 'hb_bits': d['parameters']['lanes']*16,
           'sites': 0, 'required_sites': 0, 'geometric_feasible': True}
    for pitch in p['pitches_um']:
        sites = math.floor(p['signal_fraction']*p['coarse_window_um2']/pitch**2)
        required = (n+1)*p['coarse_bits']
        yield {'partition': 'coarse', 'pitch_um': pitch, 'hb_bits': p['coarse_bits'],
               'sites': sites, 'required_sites': required, 'geometric_feasible': sites >= required}
        sites = math.floor(p['signal_fraction']*p['local_window_um2']/pitch**2)
        for width in p['local_widths_bits']:
            required = width+8+8  # request + completion, both serialized payloads
            yield {'partition': 'local_scratch', 'pitch_um': pitch, 'hb_bits': width,
                   'sites': sites, 'required_sites': required, 'geometric_feasible': sites >= required}


def validate_command(p, cmd):
    exact_keys(cmd, {'op','a','b','sa','sb','vectors','dst'})
    if cmd['op'] not in OPS: raise ValueError('Unsupported PE opcode')
    integer(cmd['vectors'],1,65535,'vectors')
    integer(cmd['dst'],0,p['shared_entries']-1,'dst')
    for base,stride in (('a','sa'),('b','sb')):
        integer(cmd[base],0,p['scratch_rows']-1,base)
        integer(cmd[stride],0,p['scratch_rows']-1,stride)
        if cmd[base]+(cmd['vectors']-1)*cmd[stride] >= p['scratch_rows']:
            raise ValueError('Descriptor would wrap a scratch address')


def encode_command(p, cmd):
    validate_command(p, cmd)
    aw,sw=bits_for(p['scratch_rows']),bits_for(p['shared_entries'])
    return pack([(OPS[cmd['op']],2)]+[(cmd[k],aw) for k in ('a','b','sa','sb')]+[(cmd['vectors'],16),(cmd['dst'],sw)])


def compile_workload(p, w):
    """Deterministic kernels and an independent scalar mathematical oracle.

    GEMM: A[PES,K] B[K,N]; B columns stored in vector rows per PE.
    Embedding: randomized table indices, reduction across the selected vector.
    Vector: alternating sum(a+b), sum(relu(a)). All results feed ME/NMC.
    """
    phases=[]; lanes=p['lanes']; k=w['vectors_per_output']; n=w['outputs_per_pe']
    if w['kernel']=='gemm' and k*(n+1)>p['scratch_rows']:
        raise ValueError('GEMM operands exceed scratch capacity')
    if w['kernel']!='gemm' and 2*n>p['scratch_rows']:
        raise ValueError('Vector/table operands exceed scratch capacity')
    for phase in range(w['phases']):
        rng=random.Random(w['seed']+phase)
        loads=[]; commands=[]; oracle={}; ops=0
        bmat=[[rng.randint(-16,15) for _ in range(n)] for _ in range(k*lanes)]
        for pe in range(p['pes']):
            cmds=[]; memory={}
            if w['kernel']=='gemm':
                avec=[rng.randint(-16,15) for _ in range(k*lanes)]
                for row in range(k): memory[row]=avec[row*lanes:(row+1)*lanes]
                for col in range(n):
                    for row in range(k): memory[k+col*k+row]=[bmat[row*lanes+j][col] for j in range(lanes)]
                    cmd={'op':'dot','a':0,'b':k+col*k,'sa':1,'sb':1,'vectors':k,'dst':pe*n+col}
                    oracle[pe*n+col]=signed(sum(avec[t]*bmat[t][col] for t in range(k*lanes)))
                    cmds.append(cmd);ops+=2*k*lanes
            else:
                for row in range(2*n): memory[row]=[rng.randint(-128,127) for _ in range(lanes)]
                addresses=list(memory);rng.shuffle(addresses)
                for col in range(n):
                    a,b=addresses[col],addresses[col+n]
                    op='add_sum' if w['kernel']=='embedding' or col%2==0 else 'relu_sum'
                    # Embedding bag uses A + a zero vector, addressing shuffled table rows.
                    if w['kernel']=='embedding': memory[b]=[0]*lanes
                    cmd={'op':op,'a':a,'b':b,'sa':0,'sb':0,'vectors':k,'dst':pe*n+col}
                    val=sum(memory[a][t]+memory[b][t] if op=='add_sum' else max(0,memory[a][t]) for t in range(lanes))
                    oracle[pe*n+col]=signed(k*val);cmds.append(cmd)
                    ops+=k*lanes*(2 if op=='add_sum' else 1)
            for cmd in cmds: validate_command(p,cmd)
            commands.append(cmds)
            loads += [{'pe':pe,'addr':addr,'data':pack([(v,8) for v in values])} for addr,values in sorted(memory.items())]
        remote=[rng.randint(-100000,100000) for _ in oracle]
        phases.append({'loads':loads,'commands':commands,'remote':remote,'oracle':oracle,
                       'result':signed(sum(oracle.values())+sum(remote)), 'useful_ops':ops+2*len(remote)})
    return phases


@dataclass
class Link:
    width:int
    bits:int
    stages:int
    cut:bool
    state:int=0
    tx:int=0
    rx:int=0
    index:int=0
    delay:int=0

    def forward(self, valid, data):
        return (self.state==3,self.rx & ((1<<self.width)-1)) if self.cut else (valid,data)

    def ready(self, downstream):
        return self.state==0 if self.cut else downstream

    def tick(self, valid, data, downstream):
        if not self.cut: return 0
        transferred=0
        if self.state==0:
            if valid: self.tx=data;self.rx=0;self.index=0;self.state=1
        elif self.state==1:
            self.rx |= (self.tx & ((1<<self.bits)-1)) << (self.index*self.bits)
            self.tx >>= self.bits;transferred=self.bits
            if self.index==(self.width+self.bits-1)//self.bits-1:
                self.delay=self.stages;self.state=2 if self.stages else 3
            else: self.index+=1
        elif self.state==2:
            if self.delay==1:self.state=3
            else:self.delay-=1
        elif downstream:self.state=0
        return transferred


class Cluster:
    def __init__(self, d, candidate):
        self.p=d['parameters'];self.n=self.p['pes'];self.l=self.p['lanes']
        self.aw=bits_for(self.p['scratch_rows']);self.sw=bits_for(self.p['shared_entries']);self.pw=bits_for(self.n)
        self.cw=2+4*self.aw+16+self.sw
        cut=PARTITIONS[candidate['partition']];stages=d['physical']['link_stages']
        coarse=d['physical']['coarse_bits'];hb=candidate['hb_bits']
        self.dma=Link(self.l*8+self.aw+self.pw,coarse,stages,cut==1)
        self.req=[Link(2*self.aw,8,stages,cut==2) for _ in range(self.n)]
        self.rsp=[Link(self.l*16,hb,stages,cut==2) for _ in range(self.n)]
        self.wb=[Link(32+self.sw,8 if cut==2 else coarse,stages,cut!=0) for _ in range(self.n)]
        self.pe=[dict(state=0,op=0,a=0,b=0,sa=0,sb=0,left=0,dst=0,acc=0) for _ in range(self.n)]
        self.mem=[{} for _ in range(self.n)];self.mem_valid=[False]*self.n;self.mem_data=[0]*self.n
        self.shared={};self.rr=0;self.locked=None
        self.me=dict(state=0,addr=0,left=0,local=0,acc=0)

    def tick(self, inp):
        """Evaluate combinational signals, then atomically apply one rising edge."""
        events=[];stalls=Counter();me=self.me;old_me=dict(me)
        old_pe=[dict(p) for p in self.pe]
        load=pack([(inp['load_data'],self.l*8),(inp['load_addr'],self.aw),(inp['load_pe'],self.pw)])
        dv,dd=self.dma.forward(inp['load_valid'],load)
        q=[];r=[];w=[]
        for j,p in enumerate(self.pe):
            q.append(self.req[j].forward(p['state']==1,p['a'] | (p['b']<<self.aw)))
            r.append(self.rsp[j].forward(self.mem_valid[j],self.mem_data[j]))
            w.append(self.wb[j].forward(p['state']==3,(p['dst']<<32)|(p['acc']&0xffffffff)))
        pick=self.locked if self.locked is not None else next((j for k in range(self.n) for j in [(self.rr+k)%self.n] if w[j][0]),None)
        wvalid=pick is not None;wdata=w[pick][1] if wvalid else 0;wa=wdata>>32
        wready=wa not in self.shared
        out={'load_ready':self.dma.ready(True),'cmd_ready':sum((p['state']==0)<<j for j,p in enumerate(self.pe)),
             'me_ready':me['state']==0,'nic_ready':me['state']==2,'out_valid':me['state']==3,
             'out_data':me['acc']&0xffffffff,'wb_valid':wvalid,'wb_ready':wready,'wb_data':wdata}
        # Snapshot old memory before DMA writes: RTL read-during-write returns old data.
        reads=[]
        for j,p in enumerate(self.pe):
            qv,qd=q[j];rv,rd=r[j];memready=not self.mem_valid[j]
            reqready=self.req[j].ready(memready)
            rspready=self.rsp[j].ready(p['state']==2)
            wbready=self.wb[j].ready(wvalid and pick==j and wready)
            if p['state']==0 and (inp['cmd_valid']>>j)&1:
                fields=unpack(inp['cmd_data']>>(j*self.cw),[2]+[self.aw]*4+[16,self.sw])
                p.update(dict(zip(['op','a','b','sa','sb','left','dst'],fields)));p['acc']=0;p['state']=1
            elif p['state']==1:
                if reqready:p['state']=2
                else:stalls['request_backpressure']+=1
            elif p['state']==2:
                if rv:
                    a=[signed(v,8) for v in unpack(rd,[8]*self.l)]
                    b=[signed(v,8) for v in unpack(rd>>(8*self.l),[8]*self.l)]
                    delta=sum(x*y if p['op']==0 else x+y if p['op']==1 else max(0,x) for x,y in zip(a,b))
                    p['acc']=signed(p['acc']+delta)
                    events.append((f'pe{j}.compute','mac_ops' if p['op']==0 else 'vector_ops',self.l*(2 if p['op']<2 else 1)))
                    if p['left']==1:p['state']=3
                    else:p['left']-=1;p['a']+=p['sa'];p['b']+=p['sb'];p['state']=1
                else:stalls['operand_wait']+=1
            elif p['state']==3:
                if wbready:p['state']=0
                else:stalls['writeback_backpressure']+=1
            # Link input must use PRE-edge PE states; q/r/w above already contain
            # the needed values for direct links, but a cut forward hides inputs.
            reads.append((j,qv,qd,memready,rspready))
        for j,old in enumerate(old_pe):
            downstream=wvalid and pick==j and wready
            for link,valid,data,ready in (
                (self.req[j],old['state']==1,old['a']|(old['b']<<self.aw),not self.mem_valid[j]),
                (self.rsp[j],self.mem_valid[j],self.mem_data[j],old['state']==2),
                (self.wb[j],old['state']==3,(old['dst']<<32)|(old['acc']&0xffffffff),downstream)):
                transferred=link.tick(valid,data,ready)
                if transferred:events.append((f'pe{j}.hb','hb_bits',transferred))
        for j,qv,qd,memready,rspready in reads:
            if self.mem_valid[j] and rspready:self.mem_valid[j]=False
            if qv and memready:
                aa,bb=unpack(qd,[self.aw,self.aw])
                if aa not in self.mem[j] or bb not in self.mem[j]: raise ValueError('Read of uninitialized scratch')
                self.mem_data[j]=self.mem[j][aa] | (self.mem[j][bb]<<(self.l*8));self.mem_valid[j]=True
                events.append((f'pe{j}.scratch','scratch_read_bytes',2*self.l))
        local_available=old_me['addr'] in self.shared
        local_value=self.shared.get(old_me['addr'],0)
        if wvalid and wready:
            self.shared[wa]=signed(wdata);self.rr=(pick+1)%self.n;self.locked=None
            events.append(('me_nmc','shared_write_bytes',4))
        elif wvalid:self.locked=pick
        if old_me['state']==0 and inp['me_valid']:
            me.update(state=1,addr=inp['me_base'],left=inp['me_count'],acc=0)
        elif old_me['state']==1:
            if local_available:
                me['local']=local_value;del self.shared[old_me['addr']];me['state']=2
                events.append(('me_nmc','shared_read_bytes',4))
            else:stalls['local_result_wait']+=1
        elif old_me['state']==2:
            if inp['nic_valid']:
                me['acc']=signed(me['acc']+me['local']+signed(inp['nic_data']))
                events.append(('me_nmc','nmc_add_ops',2))
                if me['left']==1:me['state']=3
                else:me['left']-=1;me['addr']+=1;me['state']=1
            else:stalls['nic_wait']+=1
        elif old_me['state']==3:
            if inp['out_ready']:me['state']=0
            else:stalls['output_backpressure']+=1
        transferred=self.dma.tick(inp['load_valid'],load,True)
        if transferred:events.append(('dma_hb','hb_bits',transferred))
        if dv:
            data,addr,pe=unpack(dd,[self.l*8,self.aw,self.pw])
            if pe>=self.n:raise ValueError('Invalid DMA PE destination')
            self.mem[pe][addr]=data;events.append((f'pe{pe}.scratch','scratch_write_bytes',self.l))
        return out,events,stalls

def io_contract(p):
    aw,sw,pw=bits_for(p['scratch_rows']),bits_for(p['shared_entries']),bits_for(p['pes'])
    cw=2+4*aw+16+sw
    inputs=[('load_data',p['lanes']*8),('load_addr',aw),('load_pe',pw),('load_valid',1),
            ('cmd_data',p['pes']*cw),('cmd_valid',p['pes']),('me_count',16),('me_base',sw),('me_valid',1),
            ('nic_data',32),('nic_valid',1),('out_ready',1)]
    outputs=[('load_ready',1),('cmd_ready',p['pes']),('me_ready',1),('nic_ready',1),('out_data',32),
             ('out_valid',1),('wb_data',32+sw),('wb_valid',1),('wb_ready',1)]
    return inputs,outputs


def simulate(d, candidate, workload, capture=False):
    if not candidate['geometric_feasible']:raise ValueError('Cannot execute an infeasible physical candidate')
    phases=compile_workload(d['parameters'],workload);sim=Cluster(d,candidate)
    input_fields,output_fields=io_contract(d['parameters'])
    cycle=0;counts=Counter();stalls=Counter();events=[];stimulus=[];writebacks=[];outputs=[]
    phase_timings=[];useful_ops=0
    for phase_id,phase in enumerate(phases):
        start=cycle;load_index=0;cmd_index=[0]*sim.n;nic_index=0;me_sent=False;launch=None
        next_hbm=cycle;next_nic=cycle;seen={}
        while True:
            if cycle>=d['max_cycles']:raise RuntimeError('Cycle budget exceeded; possible deadlock or undersized budget')
            if launch is None and load_index==len(phase['loads']) and sim.dma.state==0:
                launch=cycle;next_nic=cycle+workload['nic_gap_cycles']
            inp={k:0 for k,_ in input_fields}
            inp['out_ready']=workload['output_stall_period']==0 or cycle%workload['output_stall_period']!=0
            if load_index<len(phase['loads']) and cycle>=next_hbm:
                load=phase['loads'][load_index]
                inp.update(load_valid=1,load_pe=load['pe'],load_addr=load['addr'],load_data=load['data'])
            if launch is not None:
                for pe in range(sim.n):
                    if cmd_index[pe]<len(phase['commands'][pe]):
                        inp['cmd_valid'] |= 1<<pe
                        inp['cmd_data'] |= encode_command(sim.p,phase['commands'][pe][cmd_index[pe]])<<(pe*sim.cw)
                inp.update(me_valid=not me_sent,me_base=0,me_count=len(phase['remote']))
                if nic_index<len(phase['remote']) and cycle>=next_nic:
                    inp.update(nic_valid=1,nic_data=phase['remote'][nic_index]&0xffffffff)
            pe_busy=sum(p['state']!=0 for p in sim.pe);me_busy=sim.me['state'] in (1,2)
            counts['pe_busy_cycles']+=pe_busy;counts['me_busy_cycles']+=int(me_busy)
            counts['pe_me_concurrent_busy_cycles']+=int(pe_busy>0 and me_busy)
            if launch is None:
                if load_index==len(phase['loads']):stalls['dma_drain_wait']+=1
                elif cycle<next_hbm:stalls['hbm_source_wait']+=1
            out,actions,stall=sim.tick(inp)
            if inp['load_valid'] and not out['load_ready']:stalls['dma_backpressure']+=1
            counts['pe_nmc_compute_same_cycle']+=int(any(a[0].endswith('.compute') for a in actions) and any(a[1]=='nmc_add_ops' for a in actions))
            stalls.update(stall)
            if capture:
                iv=pack([(inp[k],width) for k,width in input_fields]);ov=pack([(out[k],width) for k,width in output_fields])
                mask=pack([((1<<width)-1 if k not in ('out_data','wb_data') or
                             out['out_valid' if k=='out_data' else 'wb_valid'] else 0,width) for k,width in output_fields])
                stimulus.append((iv,ov,mask))
            for unit,kind,count in actions:
                counts[kind]+=count;events.append({'cycle':cycle,'unit':unit,'action':kind,'count':count})
            if inp['load_valid'] and out['load_ready']:
                load_index+=1;next_hbm=cycle+workload['hbm_gap_cycles'];counts['hbm_bytes']+=sim.l
            elif launch is None:stalls['load_phase_wait']+=1
            for pe in range(sim.n):
                if (inp['cmd_valid'] & out['cmd_ready'])>>pe & 1:cmd_index[pe]+=1
            if inp['me_valid'] and out['me_ready']:me_sent=True
            if inp['nic_valid'] and out['nic_ready']:
                nic_index+=1;next_nic=cycle+workload['nic_gap_cycles'];counts['nic_bytes']+=4
            if out['wb_valid'] and out['wb_ready']:
                addr=out['wb_data']>>32;value=signed(out['wb_data'])
                if addr in seen or phase['oracle'].get(addr)!=value:raise AssertionError('PE result fails independent scalar oracle')
                seen[addr]=value;writebacks.append({'cycle':cycle,'phase':phase_id,'address':addr,'value':value})
            finished=out['out_valid'] and inp['out_ready'];cycle+=1
            if finished:
                if seen!=phase['oracle'] or signed(out['out_data'])!=phase['result'] or nic_index!=len(phase['remote']):
                    raise AssertionError('Collective result/membership fails independent scalar oracle')
                outputs.append({'cycle':cycle-1,'phase':phase_id,'value':signed(out['out_data'])})
                phase_timings.append({'phase':phase_id,'start':start,'launch':launch,'end':cycle})
                useful_ops+=phase['useful_ops'];break
    result={'cycles':cycle,'useful_ops':useful_ops,'counts':dict(counts),'stalls':dict(stalls),
            'writebacks':writebacks,'outputs':outputs,'phases':phase_timings,'events':events,
            'correctness':'PASS','timing_scope':'cycle model of the exported descriptor subsystem; not vendor timing'}
    return (result,stimulus) if capture else result
