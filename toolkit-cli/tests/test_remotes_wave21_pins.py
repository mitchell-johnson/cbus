"""Wave-21 offline pins for wireless project remotes (P5.07).

Each test pins a branch of ``toolkit-cli/src/cbus_toolkit/wireless_project_remotes.py``
with zero prior test refs (verified via ``grep -rn --fixed-strings`` across
``tests/`` before writing; each exact string below returned 0 hits):
- ``Invalid source SHA-256`` (``_sha``).
- ``Ambiguous or nonscalar `` (``_field`` shape guard).
- ``Invalid database Address`` (``_address``).
- ``Expected valid UTF-8 XML`` (``_parse`` decode guard; the inner
  ``Expected UTF-8 XML encoding`` raise is unreachable because
  ``RemoteCreationError`` subclasses ``ValueError`` and the surrounding
  ``except (ValueError, ...)`` remaps it, so the observable pin is the
  remapped message).
- ``Project requires a native 1..8 character identity``.
- ``Project requires unique network addresses``.
- ``Invalid frozen remote project`` (``FrozenRemoteProject.from_dict`` format guard).
- ``Expected a CBusUnits catalogue``.
- ``WTXU catalogue alternatives are outside the admitted profile``.
- ``Unsupported remote catalogue profile`` (``RemoteCatalogue.from_dict``).

Synthetic XML only; no hardware, vendor EXE, C-Gate server, or radio.
"""
import unittest

from cbus_toolkit.wireless_project_remotes import (
    CATALOGUE_FORMAT,
    FrozenRemoteProject,
    RemoteCatalogue,
    RemoteCreationError,
)


CATALOGUE = (
    b'<CBusUnits><Units><Unit><CatalogNumber>5888TXBA</CatalogNumber>'
    b'<FirmwareRevisions><Revision><UnitType>WTXU</UnitType><MinVersion>0</MinVersion>'
    b'<MaxVersion>9</MaxVersion><UnitSpecName>WTXU.xml</UnitSpecName>'
    b'<ClassName>CBusPCI</ClassName><IsDefault>true</IsDefault></Revision>'
    b'</FirmwareRevisions><InputCount>0</InputCount><OutputCount>0</OutputCount>'
    b'<GroupCount>0</GroupCount><IsAddressable>false</IsAddressable>'
    b'</Unit></Units></CBusUnits>'
)


def base_project(*networks):
    if not networks:
        networks = (
            '<Network><Address>254</Address><TagName>Source</TagName>'
            '<Unit><Address>200</Address><TagName>Gateway</TagName>'
            '<UnitType>WGATE5F</UnitType></Unit></Network>',
        )
    return (
        '<Project><Address>TEST</Address><TagName>Synthetic</TagName>'
        + ''.join(networks) + '</Project>'
    ).encode()


class RemotesWave21Pins(unittest.TestCase):
    def test_source_sha_guard_rejects_non_hex(self):
        for bad in ('', 'xyz', 'a' * 63, 'A' * 64, 'g' * 64, None, 42):
            with self.subTest(sha=bad), self.assertRaisesRegex(
                RemoteCreationError, 'Invalid source SHA-256'
            ):
                RemoteCatalogue(bad)

    def test_field_shape_database_address_and_encoding_guards(self):
        ambiguous = base_project().replace(
            b'<Address>TEST</Address>',
            b'<Address>TEST</Address><Address>TEST2</Address>',
            1,
        )
        with self.assertRaisesRegex(RemoteCreationError, 'Ambiguous or nonscalar Address'):
            FrozenRemoteProject.from_xml(ambiguous)
        nonscalar = base_project().replace(
            b'<Address>TEST</Address>', b'<Address Foo="1">TEST</Address>', 1
        )
        with self.assertRaisesRegex(RemoteCreationError, 'Ambiguous or nonscalar Address'):
            FrozenRemoteProject.from_xml(nonscalar)
        bad_address = base_project(
            '<Network><Address>abc</Address><TagName>Source</TagName></Network>'
        )
        with self.assertRaisesRegex(RemoteCreationError, 'Invalid database Address'):
            FrozenRemoteProject.from_xml(bad_address)
        latin1 = b'\xff'
        with self.assertRaisesRegex(RemoteCreationError, 'Expected valid UTF-8 XML'):
            FrozenRemoteProject.from_xml(latin1)

    def test_project_identity_network_uniqueness_and_frozen_format_guards(self):
        too_long = base_project().replace(b'>TEST<', b'>TOOLONGNAME123<', 1)
        with self.assertRaisesRegex(
            RemoteCreationError, r'Project requires a native 1\.\.8 character identity'
        ):
            FrozenRemoteProject.from_xml(too_long)
        duplicate_networks = base_project(
            '<Network><Address>254</Address><TagName>A</TagName></Network>',
            '<Network><Address>254</Address><TagName>B</TagName></Network>',
        )
        with self.assertRaisesRegex(
            RemoteCreationError, 'Project requires unique network addresses'
        ):
            FrozenRemoteProject.from_xml(duplicate_networks)
        with self.assertRaisesRegex(RemoteCreationError, 'Invalid frozen remote project'):
            FrozenRemoteProject.from_dict(
                {'format': 'bad', 'xml': '', 'source_sha256': 'x', 'facts_sha256': 'y'}
            )

    def test_catalogue_profile_guards(self):
        with self.assertRaisesRegex(RemoteCreationError, 'Expected a CBusUnits catalogue'):
            RemoteCatalogue.from_xml(b'<Project><Address>TEST</Address></Project>')
        with_alternatives = CATALOGUE.replace(
            b'<CatalogNumber>5888TXBA</CatalogNumber>',
            b'<CatalogNumber>5888TXBA</CatalogNumber>'
            b'<AlternativeCatalogNumbers>FOO</AlternativeCatalogNumbers>',
        )
        self.assertNotEqual(with_alternatives, CATALOGUE)
        with self.assertRaisesRegex(
            RemoteCreationError, 'WTXU catalogue alternatives are outside the admitted profile'
        ):
            RemoteCatalogue.from_xml(with_alternatives)
        with self.assertRaisesRegex(
            RemoteCreationError, 'Unsupported remote catalogue profile'
        ):
            RemoteCatalogue.from_dict(
                {'format': CATALOGUE_FORMAT, 'source_sha256': 'a' * 64, 'profile': {}}
            )


if __name__ == '__main__':
    unittest.main()
