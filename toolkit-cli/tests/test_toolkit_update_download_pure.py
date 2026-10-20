"""Pure-offline URL/file-name guards for catalogue-bound downloads (P9.03-P9.04).

Direct unit coverage for the two zero-ref pure helpers in
``toolkit_update_download.py``: ``_safe_file_name`` (line 71) and ``_https_url``
(line 83). No catalogue report, TLS server, network, registry or hardware is
used; both helpers are ``urllib`` + regex only.
"""
from __future__ import annotations

import unittest

from cbus_toolkit.toolkit_update_download import (
    UpdateDownloadError,
    _https_url,
    _safe_file_name,
)


class DownloadPureGuardTests(unittest.TestCase):
    def test_safe_file_name_accepts_plain_and_decoded_names(self):
        self.assertEqual(_safe_file_name("/ok/Owned-Setup.exe"), "Owned-Setup.exe")
        self.assertEqual(_safe_file_name("/Owned-Setup.exe"), "Owned-Setup.exe")
        self.assertEqual(_safe_file_name("/ok/Owned%20Setup.exe"), "Owned Setup.exe")
        self.assertEqual(_safe_file_name("/ok/good (+1).exe"), "good (+1).exe")

    def test_safe_file_name_refuses_traversal_reserved_and_shape(self):
        for path in (
            "",
            "/",
            "/ok/..",
            "/ok/a..b.exe",
            "/ok/CON",
            "/ok/con.exe",
            "/ok/PRN.txt",
            "/ok/name.",
            "/ok/name ",
            "/ok/.hidden",
            "/ok/bad|name.exe",
            "/ok/" + "a" * 201,
        ):
            with self.subTest(path=path), self.assertRaises(UpdateDownloadError):
                _safe_file_name(path)

    def test_https_url_accepts_absolute_https_and_normalizes(self):
        host, port, target, path = _https_url("https://downloads.invalid/ok/Owned-Setup.exe")
        self.assertEqual((host, port, target, path),
                         ("downloads.invalid", 443, "/ok/Owned-Setup.exe", "/ok/Owned-Setup.exe"))
        host, port, target, path = _https_url("https://DOWNLOADS.INVALID:8443/ok/x.exe?q=1")
        self.assertEqual(host, "downloads.invalid")
        self.assertEqual(port, 8443)
        self.assertEqual(target, "/ok/x.exe?q=1")
        self.assertEqual(path, "/ok/x.exe")

    def test_https_url_refuses_non_https_credentials_fragment_and_shape(self):
        for url in (
            "http://downloads.invalid/ok/x.exe",
            "https://user@downloads.invalid/ok/x.exe",
            "https://user:pass@downloads.invalid/ok/x.exe",
            "https://downloads.invalid/ok/x.exe#frag",
            "https://downloads.invalid/ok/x.exe withspace",
            "https://downloads.invalid",
            "https://downloads.invalid:99999/ok/x.exe",
            "not a url",
            "",
        ):
            with self.subTest(url=url), self.assertRaises(UpdateDownloadError):
                _https_url(url)


if __name__ == "__main__":
    unittest.main()
