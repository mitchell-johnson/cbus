# Native C-Gate TLS

The existing Python CLI successfully connected to unmodified C-Gate **3.4.0
(build 2001)** over verified mutual TLS. The acceptance run negotiated TLS 1.3
with `TLS_AES_256_GCM_SHA384`, using Python 3.12.14/OpenSSL 3.5.8 and generated
RSA-2048/SHA-256 certificates. It executed `NOOP` and created, edited, saved,
closed, and deleted a disposable project through the CLI.

Five independent failures were verified: missing, untrusted, and expired client
certificates; an untrusted server certificate; and a server hostname mismatch.
Each failed through the CLI and at the TLS layer. A subsequent valid connection
succeeded. Certificate verification and hostname checks remained enabled.

## Using configured certificates

```sh
cbus-toolkit cgate --host cbus.example --tls \
  --ca server-ca.pem --cert client-chain.pem --key client.key exec NOOP
```

`--ca` supplies the CA trusted for the server. The server certificate must permit
server authentication and identify the hostname in its subject alternative
names. `--cert` and `--key` supply the client's certificate chain and private key;
the native server must trust that client's CA. The secure command port defaults
to 20123. C-Gate access permissions still apply after TLS authentication.

Exact native implementation details were checked in the case-sensitive vendor
decompilation archive `research/vendor/cgate-decompiled.tar`:

- `Ba.java` enables TLS 1.2 and 1.3 and requires client authentication. It reads
  both its server identity and client trust anchors from the JKS file
  `key/cis.ks`, relative to the server working directory. Its store and key
  password is a fixed vendor format constant, `amazing`.
- `secure.bind-address` and `secure.port-base` select the secure listener.
  `pl.java` marks the old `secure.enable`, `secure.client-auth`, and configurable
  keystore/password properties obsolete; they do not configure this listener.
- `com/clipsal/cgate/sys/AccessContext.java` inspects the final peer-chain
  certificate's Authority Key Identifier extension without a null check.
  Our initial generated CA lacked this extension: TLS connected, but no C-Gate
  greeting arrived. Giving the generated CA a normal self-referencing AKI
  produced a working session. No vendor identity or privileged AKI was copied.

The vendor manual's sections 4.3.6 and 4.6.4.73–74 describe the secure interfaces
and port configuration. The acceptance test proves the command interface;
secure event, status, and configuration interfaces remain separate coverage.

## Bundled keystore limitation

A read-only certificate metadata inspection found that the bundled
`cgateserver` leaf uses RSA-2048/SHA-256, but its extended key usages are
`clientAuth` and `emailProtection`, with no subject alternative names. That
identity does not meet the normal server-authentication and hostname
requirements above. This is a metadata finding, not a successful verified
connection using the bundled identity. The native acceptance uses newly
generated certificates and does not extract or reuse bundled private keys.

No certificate validation, hostname verification, or cipher defaults are
weakened to accommodate the bundled identity.

## Reproducing the acceptance

Install the `research` extra, extract the matching vendor C-Gate, and have
Docker available. Use a current Python/OpenSSL build. From the repository root:

```sh
CBUS_NATIVE_TLS_TEST=1 \
CBUS_NATIVE_TLS_REPORT=toolkit-cli/research/runtime/native-tls-acceptance.json \
PYTHONPATH=toolkit-cli/src \
python3 -m unittest discover -s toolkit-cli/tests -p test_native_tls.py -v
```

Alternatively run `toolkit-cli/research/verify_tls.py`, which accepts
`--vendor-dir` and `--output`. The test pins the Java image by digest, creates
its own uniquely named container and generated PKI, and publishes only an
ephemeral TLS port on loopback. It removes the container and temporary keys
afterward. It does not use the shared native oracle or open any C-Bus network.

The permanent compact evidence is
[`native-tls-acceptance.json`](../research/fixtures/native-tls-acceptance.json).
Full rerun output is written only to the selected runtime report.
