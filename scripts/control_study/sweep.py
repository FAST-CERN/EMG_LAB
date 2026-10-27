"""Offline simulation envelope study. Overrides limits ONLY inside these trials."""
import argparse
from datetime import datetime,timezone,timedelta
import hashlib,json,math,sys,time
from pathlib import Path
import numpy as np
import mujoco

PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT))
from emg_lab.physics.simulation import Simulation,POLICY_DT
from emg_lab.physics.commands import Command


def request(sim,vector):
    """Use actual policy/slew/heading hold, but explore outside current app limits."""
    sim.set_velocity(vector)
    sim.command_velocity=np.array(vector,dtype=float)


def configure(sim,seed,condition='nominal'):
    sim.reset()
    rng=np.random.default_rng(seed)
    yaw=rng.uniform(-math.pi,math.pi)
    sim.data.qpos[3:7]=[math.cos(yaw/2),0,0,math.sin(yaw/2)]
    sim.data.qpos[7:]+=rng.normal(0,.004,size=29)
    floor=sim.model.geom('floor').id
    if not hasattr(sim,'trial_friction_original'):
        sim.trial_friction_original=sim.model.geom_friction.copy()
    sim.model.geom_friction[:]=sim.trial_friction_original
    # Scale BOTH floor and robot contact geoms: MuJoCo otherwise chooses the larger coefficient.
    if condition=='low_friction':sim.model.geom_friction[:,0]*=.7
    if condition=='high_friction':sim.model.geom_friction[:,0]*=1.3
    mujoco.mj_forward(sim.model,sim.data)
    request(sim,(0,0,0))
    for _ in range(150):sim.step()
    if condition=='perturbed':
        sim.data.qvel[:2]+=rng.uniform(-.12,.12,size=2)
        sim.data.qvel[5]+=rng.uniform(-.15,.15)
        mujoco.mj_forward(sim.model,sim.data)


def run_case(sim,name,segments,seed,condition='nominal',mode='continuous'):
    configure(sim,seed,condition)
    minimum=100.;tilts=[];samples=[];stops=[];failure=None;count=0
    for index,(vector,duration) in enumerate(segments):
        if mode=='fixed':
            vector=np.asarray(vector,dtype=float)
            active=np.flatnonzero(vector)
            if len(active)>1:raise ValueError('Fixed command cannot combine axes')
            command=Command.STOP if not len(active) else (
                Command.FORWARD if vector[0]>0 else Command.BACKWARD if vector[0]<0 else
                Command.STRAFE_LEFT if vector[1]>0 else Command.STRAFE_RIGHT if vector[1]<0 else
                Command.LEFT if vector[2]>0 else Command.RIGHT)
            class TrialSettings:
                def velocity(self,command):return tuple(vector)
            sim.set_command(command,TrialSettings())
        else:
            request(sim,vector)
        begin_xy=sim.data.qpos[:2].copy()
        last_yaw=sim.yaw
        yaw_total=max_yaw_drift=0.
        stop=bool(index and np.linalg.norm(vector)==0)
        local=[];max_drift=0.
        for step in range(round(duration/POLICY_DT)):
            try:status=sim.step()
            except Exception as e:failure=str(e);break
            count+=1
            minimum=min(minimum,status['height'])
            tilts.append(status['tilt_deg'])
            actual=[status['forward_actual'],status['lateral_actual'],status['yaw_actual']]
            local.append(actual)
            if stop:
                max_drift=max(max_drift,float(np.linalg.norm(sim.data.qpos[:2]-begin_xy)))
                delta=status['yaw']-last_yaw
                yaw_total+=math.atan2(math.sin(delta),math.cos(delta))
                max_yaw_drift=max(max_yaw_drift,abs(yaw_total))
                last_yaw=status['yaw']
            if status['fallen'] or status['tilt_deg']>55 or status['height']<.45:
                failure='fall_or_large_tilt';break
        if local:
            array=np.asarray(local)
            tail=array[-min(100,len(array)):]
            samples.append(dict(vector=list(vector),seconds=duration,mean_actual=tail.mean(axis=0).tolist(),
                std_actual=tail.std(axis=0).tolist(),peak_horizontal=float(np.max(np.linalg.norm(array[:,:2],axis=1)))))
            if stop:
                settle=None
                for end in range(25,len(array)+1):
                    block=array[end-25:end]
                    if np.linalg.norm(block[:,:2].mean(axis=0))<.07 and abs(block[:,2].mean())<.10:
                        settle=end*POLICY_DT;break
                stops.append(dict(duration_s=duration,settle_s=settle,max_drift_m=max_drift,max_yaw_drift_deg=math.degrees(max_yaw_drift)))
        if failure:break
    result=dict(name=name,seed=seed,condition=condition,sim_seconds=round(count*POLICY_DT,3),
        min_height=minimum,max_tilt=max(tilts,default=90),tilt_p95=float(np.percentile(tilts,95)) if tilts else 90,
        failure=failure,segments=samples,stops=stops)
    result['stable']=not failure and minimum>=.55 and result['max_tilt']<=35
    eligible=[v for v in stops if v['duration_s']>=3]
    result['stop_ok']=len(eligible)==sum(i>0 and d>=3 and np.linalg.norm(v)==0 for i,(v,d) in enumerate(segments)) and all(v['settle_s'] is not None and v['settle_s']<=2.5 and v['max_drift_m']<=.55 for v in eligible)
    return result


def source_hashes():
    names=['emg_lab/physics/simulation.py','emg_lab/physics/commands.py','emg_lab/physics/policy.py',
           'assets/policies/GR00T-WholeBodyControl-Walk.onnx','assets/policies/GR00T-WholeBodyControl-Balance.onnx']
    return {n:hashlib.sha256((PROJECT/n).read_bytes()).hexdigest() for n in names}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    sim=Simulation(coin=True)
    vectors=[]
    for speed in (.2,.4,.6,.8,1.,1.2,1.4,1.6):vectors.append(('forward',speed,(speed,0,0)))
    for speed in (.15,.25,.35,.45,.6,.75,1.):vectors.append(('backward',speed,(-speed,0,0)))
    for sign,name in [(1,'left_strafe'),(-1,'right_strafe')]:
        for speed in (.15,.25,.35,.45,.6,.75,1.):vectors.append((name,speed,(0,sign*speed,0)))
    for sign,name in [(1,'left_turn'),(-1,'right_turn')]:
        for speed in (.4,.8,1.2,1.6,2.,2.5):vectors.append((name,speed,(0,0,sign*speed)))
    start=time.monotonic();results=[]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    for axis,speed,vector in vectors:
        for repeat in range(3):
            result=run_case(sim,f'{axis}_{speed}',[(vector,8),((0,0,0),4)],20261025+repeat)
            result.update(axis=axis,speed=speed,repeat=repeat)
            results.append(result)
        group=results[-3:]
        print(json.dumps(dict(axis=axis,speed=speed,stable=sum(r['stable'] for r in group),
            stopped=sum(r['stop_ok'] for r in group),max_tilt=round(max(r['max_tilt'] for r in group),2),
            actual=np.mean([r['segments'][0]['mean_actual'] for r in group],axis=0).round(3).tolist())),flush=True)
        args.output.write_text(json.dumps(dict(state='in_progress',results=results),indent=2),encoding='utf-8')
    report=dict(state='complete',date=datetime.now(timezone(timedelta(hours=8))).isoformat(),
        protocol='3 yaw/joint-noise initializations per command, 3s stand + 8s motion + 4s stop; simulation-only limits override.',
        criteria=dict(min_height=.55,max_tilt=35,stop_settle_s=2.5,stop_drift_m=.55),
        source_hashes=source_hashes(),results=results,wall_seconds=time.monotonic()-start)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':main()
