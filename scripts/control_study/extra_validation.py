"""Validate proposed lower fixed tier and compare route times at both tiers."""
from pathlib import Path
from itertools import permutations
import json,math,sys,time
import numpy as np
from sweep import Simulation,run_case

def main():
    sim=Simulation(coin=True);results=[]
    fixed=[(0,0,0),(0,0,1.),(0,0,-1.),(.6,0,0),(-.4,0,0),(0,.4,0),(0,-.4,0)]
    for condition in ('nominal','low_friction','high_friction','perturbed'):
        for seed in (111,222,333):
            for i,v in enumerate(fixed[1:],1):
                r=run_case(sim,f'fixed_{i}',[(v,8),((0,0,0),4)],seed,condition,'fixed')
                r.update(category='axis',class_id=i);results.append(r)
            segments=[]
            for a,b in permutations(fixed,2):segments.extend([(a,.8),(b,.8),((0,0,0),.4)])
            segments.append(((0,0,0),4))
            r=run_case(sim,'fixed_42',segments,seed,condition,'fixed');r['category']='switches';results.append(r)
        print(condition+' fixed tier complete',flush=True)
    Path('fixed_tier_validation.json').write_text(json.dumps(dict(state='complete',results=results),indent=2),encoding='utf-8')
    print(json.dumps(dict(cases=len(results),stable=sum(r['stable'] for r in results),stopped=sum(r['stop_ok'] for r in results))),flush=True)

if __name__=='__main__':main()
