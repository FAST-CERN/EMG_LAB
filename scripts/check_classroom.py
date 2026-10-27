"""Local software self-check; does not connect to EMG or drive physical devices."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--render',action='store_true');args=parser.parse_args()
    from emg_lab.version import VERSION
    from emg_lab.physics.simulation import Simulation
    from emg_lab.hand.model import HandModel
    from emg_lab.network import LiteCNN1D
    import numpy as np,torch,onnxruntime,mujoco
    model=LiteCNN1D(4,500,4).eval()
    with torch.no_grad():assert tuple(model(torch.zeros(1,4,500)).shape)==(1,4)
    sim=Simulation(coin=True)
    for _ in range(150):status=sim.step()
    assert not status['fallen']
    hand=HandModel();hand.set_progress(.5)
    rendered=[]
    if args.render:
        for label,m,d in [('robot',sim.model,sim.data),('hand',hand.model,hand.data)]:
            with mujoco.Renderer(m,height=240,width=320) as renderer:
                renderer.update_scene(d);pixels=renderer.render();assert pixels.shape==(240,320,3)
                rendered.append(label)
    result=dict(version=VERSION,software_check='passed',rendered=rendered,python=sys.version,
                torch=torch.__version__,onnxruntime=onnxruntime.__version__,mujoco=mujoco.__version__,
                real_device_check='not_run')
    output=ROOT/'local/classroom_check.json';output.parent.mkdir(exist_ok=True);output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('Software check passed. Result: '+str(output))

if __name__=='__main__':main()
