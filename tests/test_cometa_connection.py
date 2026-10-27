"""Regression tests for SDK connection failures; never access a real DAQ."""
import sys
from unittest.mock import Mock
import pytest

if sys.platform!='win32':
    pytest.skip('真机采集链（pythonnet + Cometa SDK）为 Windows 全功能档专属，见 ADR 0002',allow_module_level=True)

from vendor.cometa import cometa_emg as module


@pytest.fixture
def daq(monkeypatch):
    fake = Mock()
    fake.get_initial_error.return_value = module.DeviceErrorEnum.SUCCESS
    fake.get_state.return_value = module.DeviceStateEnum.IDLE
    fake.get_num_installed_sensors.return_value = 16
    monkeypatch.setattr(module, 'CometaDaqSystem', lambda: fake)
    return fake


def test_missing_driver_stops_before_configuring_sensors_and_disposes(daq):
    daq.get_state.return_value = module.DeviceStateEnum.NOT_CONNECTED
    core = module.CometaEMGCore(sensors=[1, 2, 3, 4], enable_bus=False)
    assert not core.connect()
    assert '代码 28' in core.last_error
    daq.set_capture_configuration.assert_not_called()
    daq.set_sensor_configuration.assert_not_called()
    daq.start_capturing.assert_not_called()
    daq.dispose.assert_called_once()
    assert core._daq is None


def test_initial_error_disposes_without_sensor_commands(daq):
    daq.get_initial_error.return_value = module.DeviceErrorEnum.DEVICE_NOTCONNECTED
    core = module.CometaEMGCore(enable_bus=False)
    assert not core.connect()
    assert '初始化失败' in core.last_error
    daq.get_state.assert_not_called()
    daq.set_sensor_configuration.assert_not_called()
    daq.dispose.assert_called_once()


def test_initializing_can_be_retried_after_timeout(daq, monkeypatch):
    daq.get_state.return_value = module.DeviceStateEnum.INITIALIZING
    core = module.CometaEMGCore(sensors=[1, 2, 3, 4], enable_bus=False)
    assert not core.connect(timeout=0)
    assert '未就绪' in core.last_error
    daq.get_state.return_value = module.DeviceStateEnum.IDLE
    monkeypatch.setattr(core, '_wait_for_sensors_ready', lambda **kwargs: True)
    assert core.connect()
    assert core.last_error == ''
    assert [call.args[0] for call in daq.enable_sensor.call_args_list] == [1, 2, 3, 4]
    assert [call.args[0] for call in daq.disable_sensor.call_args_list] == list(range(1, 17))
    core.disconnect()
    assert [call.args[0] for call in daq.disable_sensor.call_args_list[-16:]] == list(range(1, 17))


def test_unready_sensors_are_reported_and_connection_is_released(daq):
    core = module.CometaEMGCore(sensors=[1, 2, 3, 4], enable_bus=False)
    assert not core.connect(timeout=0)
    assert '[1, 2, 3, 4]' in core.last_error
    daq.stop_capturing.assert_called_once()
    daq.dispose.assert_called_once()
    assert core._daq is None
