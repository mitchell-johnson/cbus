#!/usr/bin/env python3

# AIDEV-NOTE: keep deps consistent; see Dockerfile/requirements.txt (anchor for AI edits)

from setuptools import setup, find_packages

deps = [
	'pyserial==3.5',
	'pyserial-asyncio==0.6',
	'lxml>=2.3.2',
	'six',
	'pydot',
	'aiomqtt>=1.0.0',
]

tests_require = [
	'pytype',
	'parameterized',
]

setup(
	name="cbus",
	version="0.2",
	description="Library and applications to interact with Clipsal CBus in Python.",
	author="Michael Farrell, Mitchell Johnson",
	author_email="mitchell@johnson.fyi",
	url="https://github.com/mitchell-johnson/cbus",
	license="LGPL3+",
	install_requires=deps,
	tests_require=tests_require,
	extras_require={'test': tests_require},
	# TODO: add scripts to this.
	packages=find_packages(),
	
	entry_points={
		'console_scripts': [
			'cbz_dump_labels = cbus.toolkit.dump_labels:main',
			'cmqttd = cbus.daemon.cmqttd:main',
			'cbus_fetch_protocol_docs = cbus.tools.fetch_protocol_docs:main',
			'cbus_decode_packet = cbus.tools.decode_packet:main',
			'cbus_simulator = simulator.run_simulator:cli',
		]
	},
	
	classifiers=[
	
	],
)

