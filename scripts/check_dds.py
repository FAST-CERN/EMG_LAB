"""Loopback-only transport check, on a domain separate from the robot default."""
import os
import time


def main():
    # Keep test packets on this host; no robot network or interface is used.
    os.environ['CYCLONEDDS_URI'] = '''<CycloneDDS><Domain><General>
      <Interfaces><NetworkInterface address="127.0.0.1"/></Interfaces>
      <AllowMulticast>false</AllowMulticast></General>
      <Discovery><Peers><Peer Address="127.0.0.1"/></Peers></Discovery>
      </Domain></CycloneDDS>'''
    from bsi_dds.dds_io import DiscreteCommandSubscriber
    from bsi_robot_base import UnitreeDdsHumanoidRobotAdapter
    adapter = UnitreeDdsHumanoidRobotAdapter(domain_id=153)
    sub = DiscreteCommandSubscriber(domain_id=153)
    try:
        assert adapter.connect(),adapter.last_error
        for host,wire in enumerate([0,2,3,1]):
            matched=False
            deadline=time.monotonic()+4
            while time.monotonic()<deadline:
                assert adapter.send_direction({'filtered_class':host,'probabilities':[.1,.2,.3,.4]})
                time.sleep(.1)
                value=sub.poll()
                if sub.last_sample is not None and value.value==wire:
                    matched=True
                    break
            assert matched,(host,wire,value)
        adapter.send_direction({'filtered_class':0})
        adapter.disconnect()
        time.sleep(1.2)
        sub.poll()  # Drain any final sample, then allow its local timeout to elapse.
        time.sleep(1.2)
        assert sub.poll().value==0
        print('PASS: original DDS adapter, 4 directions, loopback domain 153, silence -> IDLE')
    finally:
        adapter.disconnect()
        sub.close()


if __name__=='__main__':
    main()
