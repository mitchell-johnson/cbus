#!/usr/bin/env python
# test_cmqttd.py - Tests for cmqttd utility functions.
# Copyright 2020 Michael Farrell <micolous+git@gmail.com>
#
# This library is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this library.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import absolute_import

from parameterized import parameterized
import io
from typing import Optional, Text, cast
import unittest

from cbus.common import Application, check_ga
from cbus.daemon import cmqttd
from cbus.daemon import topics


class CmqttdUtilityTest(unittest.TestCase):

    def test_ga_range(self):
        """Tests for ga_range()"""
        valid_ga = list(cmqttd.ga_range())

        # Should be 256 valid GAs, and they should each appear once.
        self.assertEqual(256, len(valid_ga))
        self.assertEqual(256, len(set(valid_ga)))

        for ga in valid_ga:
            check_ga(ga)  # throws exception on error

    @parameterized.expand([(ga,) for ga in cmqttd.ga_range()])
    def test_valid_topic_group_address(self, ga):
        # name is also the expected group address number
        light_topic = f'homeassistant/light/cbus_{ga}'
        light_topic_len = len(light_topic)
        bin_topic = f'homeassistant/binary_sensor/cbus_{ga}'
        bin_topic_len = len(bin_topic)

        # base topic path -> ga
        self.assertEqual((ga,Application.LIGHTING), cmqttd.get_topic_group_address(light_topic))

        # Generating a set topic
        set_topic = topics.set_topic(ga,Application.LIGHTING)
        self.assertEqual(light_topic, set_topic[:light_topic_len])
        self.assertEqual((ga,Application.LIGHTING), cmqttd.get_topic_group_address(set_topic))

        # Generating a state topic
        state_topic = topics.state_topic(ga,Application.LIGHTING)
        self.assertEqual(light_topic, state_topic[:light_topic_len])
        self.assertEqual((ga,Application.LIGHTING), cmqttd.get_topic_group_address(state_topic))

        # Generating a conf topic
        conf_topic = topics.conf_topic(ga,Application.LIGHTING)
        self.assertEqual(light_topic, conf_topic[:light_topic_len])
        self.assertEqual((ga,Application.LIGHTING), cmqttd.get_topic_group_address(conf_topic))

        # Ensure all the topics are unique
        self.assertNotEqual(set_topic, state_topic)
        self.assertNotEqual(state_topic, conf_topic)
        self.assertNotEqual(conf_topic, set_topic)

        # Binary sensors are read only, so get_topic_group_address doesn't
        # support them.
        bin_state_topic = topics.bin_sensor_state_topic(ga,Application.LIGHTING)
        self.assertTrue(bin_topic, bin_state_topic[:bin_topic_len])

        bin_conf_topic = topics.bin_sensor_conf_topic(ga,Application.LIGHTING)
        self.assertTrue(bin_topic, bin_conf_topic[:bin_topic_len])

        # Uniqueness check
        self.assertNotEqual(bin_state_topic, bin_conf_topic)

    @parameterized.expand([
        'homeassistant/light/cbus_not-a-number',
        'homeassistant/light/cbus_9000',  # out of range
        'homeassistant/light/my_light',
        'light/my_light',
    ])
    def test_invalid_topic_group_address(self, topic):
        self.assertRaises(ValueError, cmqttd.get_topic_group_address, topic)
