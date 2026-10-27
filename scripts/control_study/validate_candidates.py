"""Stress tests for a task-appropriate candidate, including box vs ellipse."""
from itertools import product,permutations
import argparse,json,math,time
from pathlib import Path
import numpy as np
from sweep import Simulation,run_case,source_hashes


def scaled(vector,caps,shape):
    values=np.asarray(vector,dtype=float)
    limits=np.array([caps[0] if values[0]>=0 else caps[1],caps[2],caps[3]])
    if shape=='box':return np.clip(values,-limits,limits).tolist()
    scale=max(1.,np.linalg.norm(values/limits))
    return (values/scale).tolist()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    sim=Simulation(coin=True)
    results=[];start=time.monotonic()
    def run(name,segments,seed,condition='nominal',mode='continuous',**meta):
        r=run_case(sim,name,segments,seed,condition,mode)
        r.update(meta);results.append(r)
        args.output.write_text(json.dumps(dict(state='in_progress',results=results),indent=2),encoding='utf-8')
        if not r['stable'] or not r['stop_ok']:print(json.dumps(dict(name=name,condition=condition,mode=mode,tilt=r['max_tilt'],last_stop=r['stops'][-1:] ,failure=r['failure'])),flush=True)
    # More accurate stopping/yaw metrics around the proposed range.
    for yaw in (.8,1.,1.2,1.4,1.6,2.):
        for sign in (-1,1):
            for seed in (111,222,333):
                run(f'turn_stop_{sign*yaw}',[((0,0,sign*yaw),6),((0,0,0),4)],seed,mode='fixed',category='turn_precision',speed=sign*yaw)
    caps=(.8,.6,.6,1.2)
    fixed=[(0,0,0),(0,0,caps[3]),(0,0,-caps[3]),(caps[0],0,0),(-caps[1],0,0),(0,caps[2],0),(0,-caps[2],0)]
    for condition in ('nominal','low_friction','high_friction','perturbed'):
        for seed in (456,789,1234):
            sequence=[]
            for a,b in permutations(fixed,2):sequence.extend([(a,.8),(b,.8),((0,0,0),.4)])
            sequence.append(((0,0,0),4))
            run('all_42_switches',sequence,seed,condition,'fixed',category='fixed_stress')
            rng=np.random.default_rng(seed)
            sequence=[(fixed[int(rng.integers(0,7))],.2) for _ in range(300)]+[((0,0,0),4)]
            run('rapid_switch_60s',sequence,seed,condition,'fixed',category='fixed_stress')
    print('fixed stress complete',flush=True)
    corners=[(x,y,z) for x,y,z in product((-caps[1],0,caps[0]),(-caps[2],0,caps[2]),(-caps[3],0,caps[3])) if np.count_nonzero((x,y,z))>=2]
    for shape in ('ellipse','box'):
        for i,raw in enumerate(corners):
            vector=scaled(raw,caps,shape)
            for seed in (456,789,1234):
                run(f'{shape}_corner_{i}',[(vector,12),((0,0,0),4)],seed,category='mixed_corners',shape=shape,raw=raw)
        for condition in ('nominal','low_friction','high_friction','perturbed'):
            for seed in (456,789,1234):
                rng=np.random.default_rng(seed)
                sequence=[(scaled(rng.uniform(-1,1,3)*[.8,.6,1.2],caps,shape),.2) for _ in range(300)]+[((0,0,0),4)]
                run(f'{shape}_random_60s',sequence,seed,condition,category='mixed_random',shape=shape)
        print(shape+' complete',flush=True)
    args.output.write_text(json.dumps(dict(state='complete',caps=dict(forward=caps[0],backward=caps[1],lateral=caps[2],yaw=caps[3]),
        criteria=dict(min_height=.55,max_tilt=35,stop_settle_s=2.5,stop_drift_m=.55),source_hashes=source_hashes(),
        results=results,wall_seconds=time.monotonic()-start),indent=2),encoding='utf-8')
    print(json.dumps(dict(cases=len(results),stable=sum(r['stable'] for r in results),stop_ok=sum(r['stop_ok'] for r in results))),flush=True)


if __name__=='__main__':main()
