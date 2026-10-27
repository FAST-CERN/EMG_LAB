"""Fairness invariants, failure scoring and immutable output mappings."""
import json
from pathlib import Path
import math
import pytest
from emg_lab.competition import Race,RaceConfig,RaceLog,make_route,digest,check_entry,load_rules,fixed_velocity,protected_files,verify_baseline,VERSION,file_hash,runtime_versions
from emg_lab.physics.commands import clamp_velocity,CommandSettings
from emg_lab.storage import write_json,ROOT


def status(xy=(0,0), seconds=0., **extra):
    return dict(position=[*xy,.75],time=seconds,fallen=False,tilt_deg=2.,**extra)


def test_route_is_precomputed_and_independent_of_trajectory():
    config=RaceConfig()
    a,b=Race(config),Race(config)
    expected=a.route.copy()
    a.start(0,0); b.start(0,0)
    for t in range(3):
        a.update(status((0,0),t),t)
        b.update(status((1,1),t),t)
    assert a.route==b.route==expected
    assert a.route_hash==b.route_hash
    assert make_route(RaceConfig(seed=config.seed+1))!=expected
    for seed in range(30):
        points=make_route(RaceConfig(seed=seed,count=20))
        assert all(max(abs(v) for v in p)<=6.5 for p in points)
        assert all(2.19<=math.dist(a,b)<=3.21 for a,b in zip([(0,0)]+points,points))


def test_completed_time_and_timeout_boundary():
    race=Race(RaceConfig(count=1,limit_s=20))
    race.start(100,3)
    race.update(status(race.target,3+19.99),119.99)
    assert race.reason=='completed'
    assert race.snapshot()['scored_seconds']==pytest.approx(19.99)
    late=Race(RaceConfig(count=1,limit_s=20)); late.start(0,0)
    late.update(status(late.target,20),20)
    assert late.reason=='timeout' and not late.collected


@pytest.mark.parametrize('reason,st',[('fallen',dict(fallen=True)),('fallen',dict(tilt_deg=61)),('out_of_bounds',dict(position=[7.21,0,.75]))])
def test_failure_penalizes_full_time(reason,st):
    race=Race(RaceConfig()); race.start(0,0)
    value=status(seconds=2); value.update(st)
    race.update(value,2)
    assert race.reason==reason
    assert race.snapshot()['scored_seconds']==120


def test_slow_machine_invalid_and_no_retry_reset():
    race=Race(RaceConfig()); race.start(0,0)
    race.update(status(seconds=.1),1)
    race.update(status(seconds=.2),3.1)
    assert race.reason=='slow_machine'
    assert not race.snapshot()['infrastructure_valid']
    with pytest.raises(ValueError): race.start(4,0)


def test_fixed_mapping_and_mixed_envelope_reject_nan():
    for i in range(7): assert CommandSettings().velocity(i)==fixed_velocity(i)
    for value in (True,3.,-1,7,'3'):
        with pytest.raises(ValueError): fixed_velocity(value)
    assert clamp_velocity((.6,0,0))==(.6,0.,0.)
    assert clamp_velocity((.8,0,1.2),'advanced')==(.8,0.,1.2)
    assert clamp_velocity((.8,0,1.2))==(.6,0.,1.)
    for tier,cap in [('basic',.6),('advanced',.8)]:
        for vector in ((99,99,99),(-99,99,-99),(.8,.6,1.2)):
            x,y,z=clamp_velocity(vector,tier)
            assert math.hypot(x,y)<=cap+1e-12
    for vector in ((float('nan'),0,0),(0,float('inf'),0),(1,2)):
        with pytest.raises(ValueError): clamp_velocity(vector)


def test_formal_rejects_mock_and_replay_before_baseline():
    config=RaceConfig(official=True)
    for source,device in [('live','模拟练习'),('replay','Cometa'),('live',None)]:
        with pytest.raises(ValueError,match='真实设备'): check_entry(config,source,dict(device=device))
    assert check_entry(RaceConfig(), 'replay',None) is None


def test_baseline_detects_code_assets_and_speed_table_changes(tmp_path):
    (tmp_path/'emg_lab').mkdir()
    (tmp_path/'emg_lab/runner.py').write_text('original')
    for name in ('main.py','requirements.txt'):(tmp_path/name).write_text('')
    write_json(tmp_path/'competition_rules.json',load_rules())
    write_json(tmp_path/'competition_approvals.json',dict(version=VERSION,entries=[]))
    write_json(tmp_path/'competition_baseline.json',dict(version=VERSION,runtime=runtime_versions(),files=protected_files(tmp_path)))
    assert verify_baseline(tmp_path)
    (tmp_path/'emg_lab/runner.py').write_text('changed')
    with pytest.raises(ValueError,match='校验不通过'):verify_baseline(tmp_path)
    rules=load_rules();rules['fixed_velocities'][3][0]=.9
    write_json(tmp_path/'competition_rules.json',rules)
    with pytest.raises(ValueError,match='速度表'):load_rules(tmp_path)


def test_early_exit_is_saved_and_changed_model_is_invalid(tmp_path):
    model=tmp_path/'model';model.mkdir()
    for name in ('model.onnx','metadata.json'):(model/name).write_text('before')
    context=dict(model=str(model),model_hashes={name:file_hash(model/name) for name in ('model.onnx','metadata.json')})
    race=Race(RaceConfig());race.start(0,0);race.finish('aborted',3.)
    log=RaceLog(race.config,context,tmp_path)
    (model/'model.onnx').write_text('after')
    path=log.finish(race)
    report=json.loads(path.with_name('result.json').read_text(encoding='utf-8'))
    assert report['reason']=='integrity_error' and not report['official_eligible']
    assert report['scored_seconds']==120 and report['state']=='finalized'


def test_worker_ignores_speed_override_and_rejects_pause():
    from emg_lab.physics.worker import SimulationWorker
    worker=SimulationWorker(dict(config=RaceConfig()))
    worker.update_command(3,CommandSettings(.1,.1))
    assert worker.settings==CommandSettings()
    with pytest.raises(ValueError):worker.set_paused(True)
    with pytest.raises(ValueError):worker.reset_scene()
    with pytest.raises(ValueError):worker.update_velocity((.1,0,0))
    continuous=SimulationWorker(dict(config=RaceConfig(control_mode='continuous')))
    continuous.update_velocity((5,5,5))
    with pytest.raises(ValueError):continuous.update_command(3,CommandSettings())


def test_coin_has_no_effect_on_robot_physics():
    import numpy as np
    from emg_lab.physics.environment import load_scene
    a,b=load_scene(ROOT/'assets'),load_scene(ROOT/'assets',coin=True)
    assert (a.nq,a.nv,a.nu)==(b.nq,b.nv,b.nu)==(36,35,29)
    np.testing.assert_array_equal(a.body_mass,b.body_mass[:a.nbody])
    np.testing.assert_array_equal(a.body_inertia,b.body_inertia[:a.nbody])
    coin=b.geom('open_coin_geom').id
    assert b.geom_contype[coin]==b.geom_conaffinity[coin]==0


def test_one_leaderboard_for_classification_and_continuous(tmp_path,monkeypatch):
    from scripts.rank_competition import rank,validate_result
    monkeypatch.setattr('emg_lab.competition.verify_baseline',lambda root=None:'trusted')
    model=tmp_path/'model';model.mkdir()
    for name in ('model.onnx','metadata.json'):(model/name).write_text('test fixture')
    context=dict(model=str(model),baseline_sha256='trusted',model_hashes={name:file_hash(model/name) for name in ('model.onnx','metadata.json')})
    paths=[]
    rules=load_rules()
    for group,mode,interval in [('分类组','fixed_classification',2),('连续组','continuous',1)]:
        for seed in rules['official_seeds']:
            race=Race(RaceConfig(seed=seed,official=True,group=group,control_mode=mode))
            log=RaceLog(race.config,context,tmp_path)
            race.start(0,0)
            for i,point in enumerate(race.route):
                now=(i+1)*interval
                st=status(point,now,requested=[0,0,0],applied=[0,0,0],effective=[0,0,0],height=.75,yaw=0.)
                race.update(st,now)
                log.record(race,st,0 if mode=='fixed_classification' else None,False,submitted=[0,0,0])
            paths.append(log.finish(race).with_name('result.json'))
    rows=rank(paths,rules,'trusted')
    assert [r['group'] for r in rows]==['连续组','分类组']
    assert [r['rank'] for r in rows]==[1,2]
    assert rows[0]['collected']==rows[1]['collected']==18
    assert rows[0]['scored_seconds']==18  # No time discount for either interface.
    for path in paths[3:]:
        report=json.loads(path.read_text(encoding='utf-8'))
        report['config']['speed_tier']='advanced'
        write_json(path,report)
    with pytest.raises(ValueError,match='验收'):rank(paths,rules,'trusted')
    monkeypatch.setattr('emg_lab.competition.load_approvals',lambda root=None:[dict(group='连续组',model_hashes=context['model_hashes'])])
    advanced=rank(paths,rules,'trusted')
    assert advanced[0]['speed_tier']=='advanced' and advanced[0]['scored_seconds']==18
    with pytest.raises(ValueError,match='可信基准'):rank(paths,rules,'wrong-baseline')
    with pytest.raises(ValueError,match='恰好'):rank(paths[:-1],rules,'trusted')
    trace=paths[0].with_name('commands.jsonl')
    lines=trace.read_text().splitlines()
    value=json.loads(lines[0]);value['requested']=[.9,0,0];lines[0]=json.dumps(value)
    trace.write_text('\n'.join(lines)+'\n')
    report=json.loads(paths[0].read_text(encoding='utf-8'));report['commands_sha256']=file_hash(trace)
    write_json(paths[0],report)
    with pytest.raises(ValueError,match='规定速度'):validate_result(paths[0],rules,'trusted')
