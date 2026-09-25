"""Strict consumption of cmqttd's synchronized KEYGL5 WidgetGroups cache."""
import unittest

from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.edlt_widget_groups import read_edlt_widget_groups, unit_path


ADDRESS = "//TEST/254/p/5"
NETWORK = "//TEST/254"
VALUES = tuple((index * 37) % 256 for index in range(44))


def reply(*lines, status=None):
    return CGateResponse(
        tuple(lines),
        lines[-1],
        int(lines[-1][:3]) if status is None else status,
    )


def widget_reply(values=VALUES, *, address=ADDRESS, attribute="WidgetGroups"):
    payload = ",".join(map(str, values))
    return reply(f"300 {address}: {attribute}={payload}")


class Client:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.commands = []

    def command(self, command):
        self.commands.append(command)
        if not self.responses:
            raise AssertionError(f"Unexpected command: {command}")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class EdltWidgetGroupsTests(unittest.TestCase):
    def test_sync_then_exact_property_read_returns_opaque_physical_cache(self):
        client = Client(reply("120-Physical synchronization in progress", "200 OK"), widget_reply())

        result = read_edlt_widget_groups(client, ADDRESS)

        self.assertEqual(
            client.commands,
            [f"NET SYNC {NETWORK}", f"GET {ADDRESS} WidgetGroups"],
        )
        self.assertEqual(result.values, VALUES)
        document = result.as_dict()
        self.assertEqual(document["format"], "cbus-edlt-widget-groups-v1")
        self.assertTrue(document["complete"])
        self.assertEqual(document["source"], "physical-synchronized-cache")
        self.assertEqual(document["widget_groups"], list(VALUES))
        self.assertEqual(document["byte_count"], 44)
        self.assertEqual(document["native_decimal_csv"], ",".join(map(str, VALUES)))
        self.assertTrue(document["opaque"])
        self.assertTrue(document["network_sync"]["completed"])
        self.assertEqual(document["network_sync"]["scope"], "entire-network")
        self.assertTrue(document["network_sync"]["read_only"])
        self.assertTrue(document["widget_groups_device_readback"])
        self.assertTrue(document["physical_observations_sequential"])
        for field in (
            "dynamic_label_cache_readback",
            "rendering_verified",
            "persistence_verified",
            "network_snapshot_atomic",
            "database_updated",
            "physical_device_modified",
        ):
            self.assertFalse(document[field], field)

    def test_unit_path_is_fully_qualified_bounded_and_canonical(self):
        self.assertEqual(unit_path("//HOUSE_1/254/p/005"), "//HOUSE_1/254/p/5")
        invalid = (
            None,
            "TEST/254/p/5",
            "//TOOLONGXX/254/p/5",
            "//TEST/256/p/5",
            "//TEST/254/P/5",
            "//TEST/254/p/256",
            "//TEST/254/56/5",
            "//TEST/254/p/5\nGET //OTHER/254/p/6 WidgetGroups",
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                unit_path(value)

    def test_sync_must_have_a_successful_well_formed_envelope(self):
        failures = (
            reply("408 Physical network synchronization failed"),
            reply("300 Not a NET SYNC completion"),
            reply("500-hidden failure", "200 OK"),
            CGateResponse(["200 OK"], "200 OK", 200),
            CGateResponse(("200 OK",), "different", 200),
        )
        for response in failures:
            with self.subTest(response=response):
                client = Client(response, widget_reply())
                with self.assertRaises((ValueError, RuntimeError)):
                    read_edlt_widget_groups(client, ADDRESS)
                self.assertEqual(client.commands, [f"NET SYNC {NETWORK}"])

    def test_get_requires_one_exact_final_300_path_and_attribute(self):
        failures = (
            widget_reply(address="//OTHER/254/p/5"),
            widget_reply(address="//TEST/253/p/5"),
            widget_reply(address="//TEST/254/p/6"),
            widget_reply(attribute="widgetgroups"),
            reply("300-" + f"{ADDRESS}: WidgetGroups=" + ",".join(map(str, VALUES)), "300 done"),
            CGateResponse((f"300 {ADDRESS}: WidgetGroups=" + ",".join(map(str, VALUES)),),
                          f"300 {ADDRESS}: WidgetGroups=" + ",".join(map(str, VALUES)), 200),
            reply("404 Parameter not found"),
        )
        for response in failures:
            with self.subTest(response=response):
                client = Client(reply("200 OK"), response)
                with self.assertRaises((ValueError, RuntimeError)):
                    read_edlt_widget_groups(client, ADDRESS)
                self.assertEqual(
                    client.commands,
                    [f"NET SYNC {NETWORK}", f"GET {ADDRESS} WidgetGroups"],
                )

    def test_payload_rejects_missing_extra_malformed_and_out_of_range_values(self):
        valid = list(VALUES)
        payloads = (
            valid[:-1],
            valid + [1],
            valid[:10] + [""] + valid[11:],
            valid[:10] + ["-1"] + valid[11:],
            valid[:10] + ["+1"] + valid[11:],
            valid[:10] + [" 1"] + valid[11:],
            valid[:10] + ["01"] + valid[11:],
            valid[:10] + ["one"] + valid[11:],
            valid[:10] + [256] + valid[11:],
            valid[:10] + [1000] + valid[11:],
        )
        for values in payloads:
            with self.subTest(values=values):
                client = Client(reply("200 OK"), widget_reply(values))
                with self.assertRaises(ValueError):
                    read_edlt_widget_groups(client, ADDRESS)
                self.assertEqual(
                    client.commands,
                    [f"NET SYNC {NETWORK}", f"GET {ADDRESS} WidgetGroups"],
                )
                self.assertEqual(client.responses, [])


if __name__ == "__main__":
    unittest.main()
