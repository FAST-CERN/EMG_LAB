"""Source-host scenery around the unchanged, policy-compatible G1 body."""
from pathlib import Path
import xml.etree.ElementTree as ET
import mujoco


def load_scene(asset_root, *, coin=False):
    root = Path(asset_root).resolve()
    robot = ET.parse(root/'g1/g1.xml').getroot()
    robot.find('compiler').set('meshdir', (root/'g1/meshes').as_posix())
    # Remove only the upstream model's example floor, lighting and sky.
    # Keep all robot bodies, joints, inertias, collision shapes and actuators.
    for child in list(robot):
        if (child.tag in ('statistic', 'visual')
                or child.tag == 'asset' and child.find("material[@name='groundplane']") is not None
                or child.tag == 'worldbody' and child.find("geom[@name='floor']") is not None):
            robot.remove(child)
    scene_root = root/'classroom'
    outdoor = ET.parse(scene_root/'outdoor_15m_scene.xml').getroot()
    robot.extend(outdoor)
    assets = ET.SubElement(robot, 'asset')
    for name, filename in [('forward', 'arrow_forward'), ('idle', 'pause_bars'),
                           ('left', 'arrow_turn_left'), ('right', 'arrow_turn_right')]:
        ET.SubElement(assets, 'mesh', name=f'ground_cue_{name}',
                      file=(scene_root/f'{filename}.obj').as_posix())
    directions = ['forward','rest','left','right','backward','strafe_left','strafe_right']
    for name in [*[f'{prefix}_{direction}' for prefix in ('cue','action') for direction in directions],
                 *[f'countdown_{i}' for i in range(4)]]:
        ET.SubElement(assets, 'texture', name=name, type='2d',
                      file=(scene_root/f'{name}.png').as_posix())
        ET.SubElement(assets, 'material', name=f'{name}_mat', texture=name, rgba='1 1 1 1')
    if coin:
        ET.SubElement(assets, 'texture', name='open_coin_logo', type='2d', file=(scene_root/'bsi_coin.png').as_posix())
        ET.SubElement(assets, 'mesh', name='open_coin_mesh', file=(scene_root/'bsi_coin.obj').as_posix())
        ET.SubElement(assets, 'material', name='open_coin_material', texture='open_coin_logo',
                      rgba='1 1 1 1', specular='0.65', metallic='0.65', roughness='0.25')
        body = ET.SubElement(ET.SubElement(robot, 'worldbody'), 'body', name='open_coin', mocap='true', pos='0 0 -2')
        ET.SubElement(body, 'geom', name='open_coin_geom', type='mesh', mesh='open_coin_mesh',
                      material='open_coin_material', contype='0', conaffinity='0', group='2')
    return mujoco.MjModel.from_xml_string(ET.tostring(robot, encoding='unicode'))
