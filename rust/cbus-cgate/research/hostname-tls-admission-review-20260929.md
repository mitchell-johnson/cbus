# C-Gate hostname and TLS command admission, 29 September 2026

The target is Schneider C-Gate 3.4.0 build 2001. The [owned probe](native_config_hostname_tls_admission_probe.py) launched thirteen disposable Java 11 children with six verified loopback listeners each. Twelve children isolated individual `CONFIG SET accept-connections-from` values; one used generated, short-lived mutual-TLS credentials. The [sanitized receipt](../../testdata/fixtures/native_cgate_config_hostname_tls_admission.json) binds the original JAR, Java runtime, harness, PKI helper, and exact probe source by SHA-256. All children exited and their temporary work directories were removed. No installed service, site project, CNI, PCI, or physical C-Bus network was contacted.

Observed with a new **IPv4** `127.0.0.1` command peer:

| Configured value | Original plain result | Original TLS result where captured |
| --- | --- | --- |
| `LOCALHOST`, `localhost.`, DNS-resolved `127.0.0.1.nip.io` | Greeting | Mutual-TLS handshake and greeting |
| `localhost 192.0.2.55`, `192.0.2.55 localhost` | Greeting | Not captured |
| `::ffff:127.0.0.1` | Greeting | Not captured |
| `ALL` | Greeting | Not captured |
| `192.0.2.55.nip.io`, `::1` | Connected, silent | TLS handshake timed out |
| `ip6-localhost`, `127.0.0.1/8`, `unresolved.invalid` | Connected, silent | Not captured |

All `CONFIG SET` calls returned `200 OK.`, and GET returned the exact stored spelling. The already admitted command session returned `200 OK` to NOOP after each SET. Setting `all` subsequently restored new greetings for the resolved wrong-address name and `::1`, but **did not** restore them after `ip6-localhost`, `127.0.0.1/8`, or `unresolved.invalid` in the captured run. This is a native failure-state observation, not a general DNS-cache or IPv6 conclusion. The second TLS child confirmed a wrong-address hostname and `::1` are rejected before TLS negotiation while the previous admitted command session can restore `all` for later TLS peers.

`cbus-cgate` now resolves hostname tokens with a two-second bound for each new command connection, matches case-insensitive `all`, normalizes IPv4-mapped IPv6 literals against IPv4 peers, and applies the policy before both plain and TLS service handlers. Numeric matches bypass DNS. Unresolvable names fail closed. The real `cmqttd` system test covers hostname variants, mapped addresses, denial/recovery, durable state, and MQTT-to-PCI continuity; a focused TLS test covers pre-handshake denial. `CMQTT CAPABILITIES` reports the bounded hostname, TLS and mapped-address slices.

This does **not** establish original IPv6-peer listener behavior, DNS refresh/cache timing, certificate identity mapping beyond prior retained captures, the event listener's admission policy, or arbitrary hostnames across platforms. `cmqttd` deliberately recovers when `all` is set after an unresolvable token; the original's observed persistent denial remains a documented compatibility difference. The probe's DNS name was observed resolving to loopback at capture time; repeatability of external DNS is not a prerequisite for the committed offline tests.
