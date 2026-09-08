"""Shared compile-time specification for evaluation and SystemVerilog generation."""
import copy
import hashlib
import itertools
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REGISTRY = {
    'int_mac_array': {'ROWS':(1,64), 'COLS':(1,64), 'DATA_W':(2,16), 'ACC_W':(4,128)},
    'banked_sram': {'BANKS':(1,64), 'DATA_W':(1,1024), 'DEPTH':(1,65536)},
    'register_file': {'LANES':(1,64), 'DATA_W':(1,128), 'DEPTH':(1,1024)},
    'stream_fifo': {'WIDTH':(1,8192), 'DEPTH':(1,1024)},
    'hb_link': {'WIDTH':(1,8192), 'STAGES':(1,16)},
    'rr_arbiter': {'PORTS':(1,64)},
}
STREAM_TYPES = {'stream_fifo', 'hb_link'}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def library_hash():
    return digest({name:hashlib.sha256((ROOT/'rtl'/f'{name}.sv').read_bytes()).hexdigest() for name in REGISTRY})


def integer(value, lo, hi, name):
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f'{name} must be an integer in [{lo}, {hi}]')


def validate_modules(design):
    if design.get('schema_version') != 1:
        raise ValueError('Unsupported module-design schema')
    if not re.fullmatch('[A-Za-z][A-Za-z0-9_]*',design.get('name','')):
        raise ValueError('Design name must be a simple identifier')
    integer(design['tile_count'],1,4096,'tile_count')
    if type(design['clock_hz']) not in (int,float) or not math.isfinite(design['clock_hz']) or not 0 < design['clock_hz'] <= 1e10:
        raise ValueError('clock_hz outside supported range')
    if not design.get('provenance'):
        raise ValueError('provenance required')
    modules = design.get('modules',[])
    if not modules:
        raise ValueError('At least one module required')
    names=set()
    for m in modules:
        name=m.get('name','')
        if not re.fullmatch('[A-Za-z][A-Za-z0-9_]*',name) or name in names:
            raise ValueError(f'Invalid/duplicate module name {name!r}')
        names.add(name)
        integer(m['tier'],0,1,name+'.tier')
        if m['type'] not in REGISTRY:
            raise ValueError(f"No RTL implementation registered for {m['type']}; no proxy substitution allowed")
        spec=REGISTRY[m['type']]; p=m['parameters']
        if set(p)!=set(spec):
            raise ValueError(f'{name}: parameters must be exactly {sorted(spec)}')
        for key,(lo,hi) in spec.items():
            integer(p[key],lo,hi,f'{name}.{key}')
        if m['type']=='int_mac_array' and p['ACC_W']<2*p['DATA_W']:
            raise ValueError('ACC_W must cover the signed product width')
        if m['type']=='banked_sram' and p['BANKS']*p['DATA_W']*p['DEPTH']>2**27:
            raise ValueError('Generic memory exceeds generation safety limit of 128 Mbit')
    byname={m['name']:m for m in modules}
    used=set()
    for c in design.get('connections',[]):
        if set(c)!={'source','target'}:
            raise ValueError('Connections require source and target module names')
        a,b=byname.get(c['source']),byname.get(c['target'])
        if a is None or b is None or a is b or a['type'] not in STREAM_TYPES or b['type'] not in STREAM_TYPES:
            raise ValueError('Only explicit FIFO/HB ready-valid stream connections supported')
        for endpoint in ((a['name'],'out'),(b['name'],'in')):
            if endpoint in used: raise ValueError('Stream fanout/multiple drivers require an explicit module')
            used.add(endpoint)
        if a['parameters']['WIDTH']!=b['parameters']['WIDTH']:
            raise ValueError('Connected widths differ; no implicit truncation or converter')
    # No cyclic ready path / hidden combinational loops.
    graph={name:[] for name in names}
    for c in design.get('connections',[]): graph[c['source']].append(c['target'])
    def visit(name,active,done):
        if name in active: raise ValueError('Cyclic stream graph not supported')
        if name in done:return
        for child in graph[name]: visit(child,active|{name},done)
        done.add(name)
    done=set()
    for name in names:visit(name,set(),done)
    return design


def variants(design,limit=2048):
    axes=[]
    for i,m in enumerate(design['modules']):
        for key,values in m.get('sweep',{}).items():
            if key not in REGISTRY.get(m['type'],{}) or not isinstance(values,list) or not values:
                raise ValueError('Invalid sweep axis')
            axes.append((i,key,values))
    count=1
    for _,_,v in axes:count*=len(v)
    if count>limit:raise ValueError(f'Sweep has {count} parameter combinations; limit={limit}')
    for values in itertools.product(*(a[2] for a in axes)):
        d=copy.deepcopy(design)
        for (i,k,_),v in zip(axes,values):d['modules'][i]['parameters'][k]=v
        for m in d['modules']:m.pop('sweep',None)
        byname={m['name']:m for m in d['modules']}
        bindings=d.get('bindings',[])
        targets=set()
        # Resolve bindings topologically, reject cycles and conflicting sweep targets.
        pending=list(bindings)
        for b in pending:
            if set(b)!={'source','target'}:raise ValueError('Binding requires source and target')
            if b['target'] in targets:raise ValueError('Duplicate binding target')
            targets.add(b['target'])
            for endpoint in (b['source'],b['target']):
                parts=endpoint.split('.')
                if len(parts)!=2 or parts[0] not in byname or parts[1] not in byname[parts[0]]['parameters']:
                    raise ValueError(f'Unknown binding parameter {endpoint}')
            if any(f"{design['modules'][i]['name']}.{k}"==b['target'] for i,k,_ in axes):
                raise ValueError('A bound target cannot also have an independent sweep')
        while pending:
            pending_targets={b['target'] for b in pending}
            ready=[b for b in pending if b['source'] not in pending_targets]
            if not ready:raise ValueError('Cyclic parameter bindings')
            for b in ready:
                s,sp=b['source'].split('.');t,tp=b['target'].split('.')
                byname[t]['parameters'][tp]=byname[s]['parameters'][sp]
                pending.remove(b)
        yield validate_modules(d)


def resources(m):
    p=m['parameters'];kind=m['type']
    out={'memory_bits':0,'state_bits':0,'macs_per_cycle':0,'read_bits_per_cycle':0,'latency_cycles':0}
    if kind=='int_mac_array':
        out.update(macs_per_cycle=p['ROWS']*p['COLS'],state_bits=2*p['ROWS']*p['COLS']*p['ACC_W']+1,latency_cycles=1)
    elif kind=='banked_sram':
        out.update(memory_bits=p['BANKS']*p['DATA_W']*p['DEPTH'],read_bits_per_cycle=p['BANKS']*p['DATA_W'],state_bits=p['BANKS']*(p['DATA_W']+1),latency_cycles=1)
    elif kind=='register_file':
        out.update(memory_bits=p['LANES']*p['DATA_W']*p['DEPTH'],read_bits_per_cycle=2*p['LANES']*p['DATA_W'])
    elif kind=='stream_fifo':
        out.update(memory_bits=p['WIDTH']*p['DEPTH'],state_bits=2*max(1,(p['DEPTH']-1).bit_length())+p['DEPTH'].bit_length(),latency_cycles=1)
    elif kind=='hb_link':out.update(state_bits=p['STAGES']*(p['WIDTH']+1),latency_cycles=p['STAGES'])
    elif kind=='rr_arbiter':out.update(state_bits=max(1,(p['PORTS']-1).bit_length()))
    return out


def ports(m):
    p=m['parameters'];kind=m['type']
    def i(name,w=1):return ('input',name,w)
    def o(name,w=1):return ('output',name,w)
    result=[i('clk'),i('rst')]
    if kind in STREAM_TYPES:
        return result+[i('in_valid'),o('in_ready'),i('in_data',p['WIDTH']),o('out_valid'),i('out_ready'),o('out_data',p['WIDTH'])]
    if kind=='int_mac_array':
        return result+[i('in_valid'),o('in_ready'),i('clear'),i('last'),i('a_data',p['ROWS']*p['DATA_W']),i('b_data',p['COLS']*p['DATA_W']),o('out_valid'),i('out_ready'),o('out_data',p['ROWS']*p['COLS']*p['ACC_W'])]
    aw=max(1,(p.get('DEPTH',1)-1).bit_length())
    if kind=='banked_sram':
        b=p['BANKS'];w=p['DATA_W']
        return result+[i('req_valid',b),i('write_enable',b),i('address',b*aw),i('write_data',b*w),o('read_valid',b),o('read_data',b*w)]
    if kind=='register_file':
        l=p['LANES'];w=p['DATA_W']
        return result+[i('write_enable',l),i('write_address',l*aw),i('write_data',l*w),i('read_address_a',l*aw),i('read_address_b',l*aw),o('read_data_a',l*w),o('read_data_b',l*w)]
    if kind=='rr_arbiter':
        n=p['PORTS']
        return result+[i('request',n),i('advance'),o('grant',n),o('grant_valid'),o('grant_index',max(1,(n-1).bit_length()))]
    raise ValueError('Unregistered module')
