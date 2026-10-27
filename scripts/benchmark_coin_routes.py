"""TEST ONLY: geometric steering checks route reachability, not EMG performance.

This script never runs in the student app and never produces official results.
"""
import argparse
import json
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from emg_lab.competition import Race,RaceConfig,load_rules
from emg_lab.physics.simulation import Simulation
from emg_lab.physics.commands import Command


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    rules=load_rules()
    sim=Simulation(coin=True)
    results=[]
    for seed in rules['official_seeds']:
        sim.reset()
        for _ in range(150): sim.step()
        race=Race(RaceConfig(seed,rules['count'],rules['limit_s']))
        start=sim.data.time
        race.start(0.,start)
        turning=True
        tilt=0.
        while not race.reason:
            dx,dy=[a-b for a,b in zip(race.target,sim.data.qpos)]
            error=math.atan2(math.sin(math.atan2(dy,dx)-sim.yaw),math.cos(math.atan2(dy,dx)-sim.yaw))
            turning=abs(error)>(.12 if turning else .32)
            command=(Command.LEFT if error>0 else Command.RIGHT) if turning else Command.FORWARD
            sim.set_command(command)
            status=sim.step()
            tilt=max(tilt,status['tilt_deg'])
            race.update(status,sim.data.time-start)
        result=dict(seed=seed,route=race.route,route_hash=race.route_hash,count=len(race.collected),
                    reason=race.reason,simulation_seconds=round(race.elapsed,3),max_tilt_deg=round(tilt,3))
        print(json.dumps(result),flush=True)
        results.append(result)
    report=dict(purpose='Reachability with test-only geometric controller; not student or EMG results.',
                all_passed=all(r['reason']=='completed' for r in results),results=results)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return 0 if report['all_passed'] else 1


if __name__=='__main__': raise SystemExit(main())
