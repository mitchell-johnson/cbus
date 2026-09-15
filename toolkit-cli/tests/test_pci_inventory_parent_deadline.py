"""Enclosing workflows cannot extend the full inventory's absolute I/O budget."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cbus_toolkit import pci_full_inventory, pci_inventory
from tests.test_pci_full_inventory import collector, mmi_result, serial_result
from tests.test_pci_serial_address_transport import Clock, FakeSocket


class InventoryParentDeadlineTests(unittest.TestCase):
    def test_nonfinite_internal_deadline_rejects_before_sequence_start(self):
        for value in (True, '1', float('nan'), float('inf'), float('-inf')):
            client=collector();client._absolute_deadline=value
            with self.subTest(value=value),patch.object(client,'_mmi_collector',side_effect=AssertionError('No child')):
                with self.assertRaises(ValueError):client.collect_inventory()
            self.assertFalse(client._used);self.assertIsNone(client.last_observation)

    def test_expired_parent_and_delayed_child_factory_start_no_child_io(self):
        for delay in (None,.3):
            client=collector();clock=Clock();clock.value=0.
            client._absolute_deadline=0. if delay is None else .2
            def factory(timeout):
                clock.value+=delay
                return SimpleNamespace(last_observation=None,collect_mmi=lambda:self.fail('Expired child ran'))
            with patch.object(pci_full_inventory,'time',SimpleNamespace(monotonic=clock)),\
                    patch.object(client,'_mmi_collector',side_effect=factory) as create:
                result=client.collect_inventory()
            self.assertEqual(create.call_count,int(delay is not None));self.assertEqual(result.request_count,0)
            self.assertEqual(result.termination,'overall_timeout');self.assertIs(result,client.last_observation)
            self.assertFalse(result.complete);self.assertIsNone(result.initial_mmi)

    def test_late_initial_and_serial_child_results_are_retained_without_next_request(self):
        for late_phase in ('mmi','serial'):
            client=collector();clock=Clock();clock.value=0.;client._absolute_deadline=.2;calls=[]
            def factory(kind,timeout):
                calls.append(kind)
                result=mmi_result() if kind=='mmi' else serial_result(16,'100966.1187')
                class Child:
                    last_observation=None
                    def collect(self):
                        self.last_observation=result
                        clock.value=.3 if kind==late_phase else .01
                        return result
                    def collect_mmi(self):return self.collect()
                    def collect_serials(self,address):return self.collect()
                return Child()
            with patch.object(pci_full_inventory,'time',SimpleNamespace(monotonic=clock)),\
                    patch.object(client,'_mmi_collector',side_effect=lambda t:factory('mmi',t)),\
                    patch.object(client,'_serial_collector',side_effect=lambda t:factory('serial',t)):
                result=client.collect_inventory()
            self.assertEqual(calls,['mmi'] if late_phase=='mmi' else ['mmi','serial'])
            self.assertIsNotNone(result.initial_mmi);self.assertIsNone(result.final_mmi)
            self.assertEqual(len(result.serial_observations),int(late_phase=='serial'))
            self.assertEqual(result.termination,'overall_timeout');self.assertFalse(result.complete)

    def test_real_mmi_child_late_connect_never_transmits_and_is_retained(self):
        client=collector();clock=Clock();clock.value=0.;client._absolute_deadline=.5
        sock=FakeSocket(clock,connect=lambda:setattr(clock,'value',.6))
        real_factory=client._mmi_collector
        def factory(timeout):
            child=real_factory(timeout);child._make_socket=lambda:sock
            return child
        with patch.object(pci_full_inventory,'time',SimpleNamespace(monotonic=clock)),\
                patch.object(pci_inventory,'time',SimpleNamespace(monotonic=clock)),\
                patch.object(client,'_mmi_collector',side_effect=factory),\
                patch.object(client,'_serial_collector',side_effect=AssertionError('No follow-up request')):
            result=client.collect_inventory()
        self.assertIsNotNone(result.initial_mmi);self.assertTrue(result.initial_mmi.connection_closed)
        self.assertEqual(result.initial_mmi.termination,'overall_timeout');self.assertFalse(result.complete)
        self.assertFalse([call for call in sock.calls if call[0] in ('sendall','recv')])
        self.assertEqual(sock.calls[-1],('close',))


if __name__=='__main__':unittest.main()
