"""Reproducible simulation experiments, not a guarantee of hardware stability."""
import argparse
from itertools import permutations
import json
from pathlib import Path
import sys
import time
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from emg_lab.physics.simulation import Simulation, POLICY_DT
from emg_lab.physics.commands import Command, CommandSettings


def run_case(sim, name, commands, settings=CommandSettings()):
    sim.reset()
    minimum, max_tilt, max_speed = 100., 0., 0.
    sim.set_command(Command.STOP)
    for _ in range(100):
        sim.step()
    count = 0
    for command, seconds in commands:
        if isinstance(command, tuple):
            sim.set_velocity(command)
        else:
            sim.set_command(command, settings)
        for _ in range(round(seconds/POLICY_DT)):
            status = sim.step()
            minimum = min(minimum, status['height'])
            max_tilt = max(max_tilt, status['tilt_deg'])
            max_speed = max(max_speed, float(np.linalg.norm(sim.data.qvel[:2])))
            count += 1
            if status['fallen'] or status['tilt_deg'] > 60:
                break
        if status['fallen'] or status['tilt_deg'] > 60:
            break
    result = dict(case=name, duration_s=round(count*POLICY_DT,2),
        min_height_m=round(minimum,4), max_tilt_deg=round(max_tilt,3),
        max_horizontal_speed_m_s=round(max_speed,4), fallen=status['fallen'],
        passed=not status['fallen'] and minimum>=.55 and max_tilt<=45)
    print(json.dumps(result), flush=True)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    sim=Simulation(coin=True)
    cases=[]
    for command in Command:
        cases.append((f'fixed_{command.name}_20s',[(command,20),(Command.STOP,3)]))
    pairs=[]
    for left,right in permutations(Command,2):
        pairs.extend([(left,1),(right,1),(Command.STOP,.5)])
    cases.append(('all_42_ordered_transitions',pairs))
    rng=np.random.default_rng(20261025)
    cases.append(('rapid_random_switch_60s',[(Command(int(rng.integers(0,7))),.2) for _ in range(300)]))
    for velocity in ((.6,0,.8),(.6,0,-.8),(-.25,0,.8),(0,.25,.8),(0,-.25,-.8),(.6,.25,.8)):
        cases.append((f'bounded_mixed_{velocity}',[(velocity,15),(Command.STOP,3)]))
    start=time.monotonic()
    results=[run_case(sim,*case) for case in cases]
    report=dict(seed=20261025,physics_dt=.005,policy_dt=.02,results=results,
        all_passed=all(r['passed'] for r in results),wall_seconds=time.monotonic()-start,
        limitation='Finite simulation cases only; no hardware guarantee or proof for every possible input sequence.')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['all_passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
