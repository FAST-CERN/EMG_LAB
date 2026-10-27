"""Test-only geometric controller; never part of students' EMG decoder."""
from pathlib import Path
import json,math,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from emg_lab.physics.simulation import Simulation
from emg_lab.physics.commands import Command
from emg_lab.competition import Race,RaceConfig

def main():
    sim=Simulation(coin=True);results=[]
    for tier in ('basic','advanced'):
        for seed in [20261025,20261026,20261027,*range(100,117)]:
            sim.reset()
            for _ in range(150):sim.step()
            race=Race(RaceConfig(seed=seed,control_mode='continuous',speed_tier=tier));start=sim.data.time
            race.start(0,start);turning=True;max_tilt=0.;height=99.
            while not race.reason:
                dx,dy=[a-b for a,b in zip(race.target,sim.data.qpos)]
                error=math.atan2(math.sin(math.atan2(dy,dx)-sim.yaw),math.cos(math.atan2(dy,dx)-sim.yaw))
                turning=abs(error)>(.12 if turning else .32)
                sim.set_velocity((0,0,(1 if error>0 else -1)*(1. if tier=='basic' else 1.2)) if turning else ((.6 if tier=='basic' else .8),0,0),tier)
                status=sim.step();max_tilt=max(max_tilt,status['tilt_deg']);height=min(height,status['height'])
                race.update(status,sim.data.time-start)
            r=dict(tier=tier,seed=seed,reason=race.reason,count=len(race.collected),seconds=round(race.elapsed,3),max_tilt=max_tilt,min_height=height)
            results.append(r);print(json.dumps(r),flush=True)
    Path('route_validation.json').write_text(json.dumps(dict(state='complete',purpose='Reachability comparison only, ideal geometric controller, no human or EMG input.',results=results),indent=2),encoding='utf-8')

if __name__=='__main__':main()
