"""Official Revo2 visual meshes and URDF kinematics, rendered with MuJoCo.

This is a pose demonstration, not a contact/force simulation. All URDF visual
meshes (including extra palm and thumb shells) and mimic joints are retained.
"""
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial.transform import Rotation
from ..storage import ROOT
from ..tasks import HAND_RATE

ASSETS = ROOT/'assets'/'revo2'
ACTIVE = ['left_'+n+'_joint' for n in (
    'thumb_proximal','thumb_metacarpal','index_proximal','middle_proximal','ring_proximal','pinky_proximal')]


class HandMotion:
    def __init__(self):
        self.progress = 0.
        self.command = 0

    def set_command(self, command):
        if command not in (0,1,2):
            raise ValueError('灵巧手指令必须为停止、张开或握合。')
        self.command = int(command)

    def advance(self, dt):
        direction = {0:0,1:-1,2:1}[self.command]
        self.progress = float(np.clip(self.progress+direction*HAND_RATE/100*max(0,dt),0,1))
        return self.progress

    @property
    def positions(self):
        return [400,337]+[round(self.progress*1000)]*4


def _origin(element):
    origin = element.find('origin')
    xyz = origin.get('xyz','0 0 0') if origin is not None else '0 0 0'
    rpy = origin.get('rpy','0 0 0') if origin is not None else '0 0 0'
    x,y,z,w = Rotation.from_euler('xyz',[float(x) for x in rpy.split()]).as_quat()
    return dict(pos=xyz,quat=' '.join(map(str,(w,x,y,z))))


class HandModel:
    def __init__(self, assets=ASSETS):
        import mujoco
        self.mujoco = mujoco
        assets = Path(assets)
        urdf = ET.parse(assets/'revo2_left_hand.urdf').getroot()
        xml = ET.Element('mujoco',model='Revo2 classroom visual')
        ET.SubElement(xml,'compiler',angle='radian',meshdir=str(assets/'meshes'))
        ET.SubElement(xml,'option',gravity='0 0 0')
        visual=ET.SubElement(xml,'visual')
        ET.SubElement(visual,'global',offwidth='800',offheight='520')
        ET.SubElement(visual,'headlight',ambient='.40 .40 .40',diffuse='.40 .40 .40',specular='.05 .05 .05')
        ET.SubElement(visual,'rgba',haze='.92 .95 .97 1')
        asset=ET.SubElement(xml,'asset')
        ET.SubElement(asset,'texture',name='sky',type='skybox',builtin='gradient',rgb1='.90 .94 .97',rgb2='.98 .99 1',width='256',height='256')
        world=ET.SubElement(xml,'worldbody')
        ET.SubElement(world,'light',pos='.3 -.3 .5',dir='-.3 .3 -.5',diffuse='.45 .45 .45')
        ET.SubElement(world,'geom',type='plane',size='1 1 .01',pos='0 0 -.023',rgba='.93 .96 .97 1')
        ET.SubElement(world,'geom',type='cylinder',size='.057 .011',pos='0 0 -.011',rgba='.16 .28 .34 1')
        links={e.get('name'):e for e in urdf.findall('link')}
        children={}
        self.mimics=[]
        for joint in urdf.findall('joint'):
            children.setdefault(joint.find('parent').get('link'),[]).append(joint)
            mimic=joint.find('mimic')
            if mimic is not None:
                self.mimics.append((joint.get('name'),mimic.get('joint'),float(mimic.get('multiplier','1')),float(mimic.get('offset','0'))))
        loaded=set()
        def add_link(parent,name,joint=None):
            body=ET.SubElement(parent,'body',name=name,**(_origin(joint) if joint is not None else {}))
            if joint is not None and joint.get('type')!='fixed':
                limits=joint.find('limit')
                ET.SubElement(body,'joint',name=joint.get('name'),type='hinge',axis=joint.find('axis').get('xyz'),
                              range=limits.get('lower')+' '+limits.get('upper'))
                ET.SubElement(body,'inertial',pos='0 0 0',mass='.01',diaginertia='0.00001 0.00001 0.00001')
            for visual in links[name].findall('visual'):
                mesh=visual.find('geometry/mesh')
                if mesh is None: continue
                filename=Path(mesh.get('filename')).name
                mesh_name=Path(filename).stem
                if mesh_name not in loaded:
                    ET.SubElement(asset,'mesh',name=mesh_name,file=filename)
                    loaded.add(mesh_name)
                color='.18 .23 .27 1' if 'touch' in filename else '.64 .73 .78 1'
                ET.SubElement(body,'geom',type='mesh',mesh=mesh_name,rgba=color,contype='0',conaffinity='0',**_origin(visual))
            for child in children.get(name,[]):
                add_link(body,child.find('child').get('link'),child)
        add_link(world,'left_base_link')
        self.xml=ET.tostring(xml,encoding='unicode')
        self.model=mujoco.MjModel.from_xml_string(self.xml)
        self.data=mujoco.MjData(self.model)
        self.camera=mujoco.MjvCamera()
        self.camera.lookat[:]=[.015,0,.075]
        self.camera.distance=.28
        self.camera.azimuth=145
        self.camera.elevation=-15
        self.set_progress(0)

    def set_progress(self, progress):
        # Thumb remains at its factory resting pose; four proximal drives share p.
        angles=np.deg2rad([24,30]+[81*float(np.clip(progress,0,1))]*4)
        # The mesh URDF rounds the finger limit to 1.41 rad, slightly below 81°.
        angles=np.array([np.clip(a,*self.model.joint(n).range) for n,a in zip(ACTIVE,angles)])
        self.set_angles(angles)

    def set_angles(self, angles):
        angles=np.asarray(angles,dtype=float)
        if angles.shape!=(6,) or not np.isfinite(angles).all():
            raise ValueError('姿态必须包含六个有限关节角。')
        for name,angle in zip(ACTIVE,angles):
            lower,upper=self.model.joint(name).range
            if not lower-1e-6 <= angle <= upper+1e-6:
                raise ValueError('预设姿态超出模型关节范围。')
            self.data.qpos[self.model.joint(name).qposadr[0]]=angle
        for name,source,mult,offset in self.mimics:
            self.data.qpos[self.model.joint(name).qposadr[0]]=self.data.qpos[self.model.joint(source).qposadr[0]]*mult+offset
        self.mujoco.mj_forward(self.model,self.data)

    def renderer(self,width=800,height=520):
        return self.mujoco.Renderer(self.model,width=width,height=height)
