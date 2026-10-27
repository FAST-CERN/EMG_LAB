import pytest
from emg_lab.competition import RaceConfig,VERSION,load_approvals,check_speed_access,protected_files
from emg_lab.storage import write_json
from emg_lab.physics.commands import clamp_velocity,CommandSettings

def test_fixed_cannot_claim_advanced_and_mixed_caps_are_explicit():
    with pytest.raises(ValueError,match='固定分类'):
        RaceConfig(speed_tier='advanced')
    assert CommandSettings().velocity(5)==(0.,.4,0.)
    assert clamp_velocity((.8,.6,1.2),'advanced')==pytest.approx((.64,.48,1.2))
    assert clamp_velocity((.6,0,1.))==(.6,0.,1.)
    with pytest.raises(ValueError):clamp_velocity((1,2,3),'unlimited')

def test_advanced_formal_access_requires_review_of_exact_group_and_model(tmp_path):
    register=tmp_path/'competition_approvals.json'
    write_json(register,dict(version=VERSION,entries=[]))
    hashes={'model.onnx':'a'*64,'metadata.json':'b'*64}
    config=RaceConfig(group='A',control_mode='continuous',speed_tier='advanced',official=True)
    with pytest.raises(ValueError,match='验收'):check_speed_access(config,dict(model_hashes=hashes),tmp_path)
    # A practice run can explore advanced control, but cannot claim an official score.
    assert check_speed_access(RaceConfig(control_mode='continuous',speed_tier='advanced'),{},tmp_path)['forward']==.8
    entry=dict(approved=True,group='A',model_hashes=hashes,capabilities=['mixed_axes'],approved_by='teacher',evidence='review record')
    write_json(register,dict(version=VERSION,entries=[entry]))
    assert check_speed_access(config,dict(model_hashes=hashes),tmp_path)['yaw']==1.2
    wrong=dict(hashes);wrong['model.onnx']='c'*64
    with pytest.raises(ValueError,match='哈希'):check_speed_access(config,dict(model_hashes=wrong),tmp_path)
    with pytest.raises(ValueError,match='验收'):
        check_speed_access(RaceConfig(group='B',control_mode='continuous',speed_tier='advanced',official=True),dict(model_hashes=hashes),tmp_path)
    entry['approved']=False
    write_json(register,dict(version=VERSION,entries=[entry]))
    assert load_approvals(tmp_path)==[]
    entry['approved']=True;entry['evidence']=''
    write_json(register,dict(version=VERSION,entries=[entry]))
    with pytest.raises(ValueError,match='证据'):load_approvals(tmp_path)
