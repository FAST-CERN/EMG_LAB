"""Final rounded-box envelope, true contact-friction perturbations and fine control."""
from itertools import product,permutations
import json,math,time
from pathlib import Path
import numpy as np
from sweep import Simulation,run_case,source_hashes


def envelope(v):
    x,y,w=np.clip(v,[-.6,-.6,-1.2],[.8,.6,1.2])
    scale=max(1.,math.hypot(x,y)/.8)
    return [x/scale,y/scale,w]


def main():
    sim=Simulation(coin=True);results=[];start=time.monotonic();path=Path('final_validation.json')
    def run(name,segments,seed,condition='nominal',mode='continuous',**meta):
        r=run_case(sim,name,segments,seed,condition,mode)
        r.update(meta);results.append(r)
        path.write_text(json.dumps(dict(state='in_progress',results=results),indent=2),encoding='utf-8')
        if not r['stable'] or not r['stop_ok']:print(json.dumps(dict(name=name,condition=condition,seed=seed,tilt=r['max_tilt'],stop=r['stops'][-1:],failure=r['failure'])),flush=True)
    for condition in ('nominal','low_friction','high_friction','perturbed'):
        corners=[v for v in product((-.6,0,.8),(-.6,0,.6),(-1.2,0,1.2)) if np.count_nonzero(v)>=2]
        for i,raw in enumerate(corners):
            run(f'corner_{i}',[(envelope(raw),15),((0,0,0),4)],700+i,condition,category='corners',raw=list(raw))
        for seed in (456,789,1234):
            rng=np.random.default_rng(seed)
            segments=[(envelope(rng.uniform(-1,1,3)*[1.,.8,1.5]),.2) for _ in range(600)]+[((0,0,0),4)]
            run('mixed_random_120s',segments,seed,condition,category='mixed_random')
            fixed=[(0,0,0),(0,0,1.2),(0,0,-1.2),(.8,0,0),(-.6,0,0),(0,.6,0),(0,-.6,0)]
            segments=[]
            for a,b in permutations(fixed,2):segments.extend([(a,.8),(b,.8),((0,0,0),.4)])
            segments.append(((0,0,0),4))
            run('fixed_all_42',segments,seed,condition,'fixed',category='fixed_stress')
        print(condition+' complete',flush=True)
    for axis,sign,label,limit in [(0,1,'forward',.8),(0,-1,'backward',.6),(1,1,'left',.6),(1,-1,'right',.6),(2,1,'yaw_left',1.2),(2,-1,'yaw_right',1.2)]:
        for fraction in (.1,.25,.5,.75,1.):
            v=[0.,0.,0.];v[axis]=sign*limit*fraction
            for seed in (111,222,333):
                run(f'amplitude_{label}_{fraction}',[(v,6),((0,0,0),4)],seed,category='amplitude',axis=axis,sign=sign,fraction=fraction)
    path.write_text(json.dumps(dict(state='complete',envelope='axis clip [-.6,-.6,-1.2]..[.8,.6,1.2], then horizontal norm <=.8, yaw independent',
        criteria=dict(min_height=.55,max_tilt=35,stop_settle_s=2.5,stop_drift_m=.55,stop_scope='stop segments >=3s only'),
        friction_protocol='All contact geom sliding coefficients multiplied by .7/1.3; other friction terms unchanged.',
        source_hashes=source_hashes(),results=results,wall_seconds=time.monotonic()-start),indent=2),encoding='utf-8')
    print(json.dumps(dict(cases=len(results),stable=sum(r['stable'] for r in results),stop_ok=sum(r['stop_ok'] for r in results))),flush=True)


if __name__=='__main__':main()
