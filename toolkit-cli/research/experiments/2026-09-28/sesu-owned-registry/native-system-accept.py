"""Disposable Windows SYSTEM HKCU test of the CLI-owned SESU registry adapter."""
import hashlib
import json
from pathlib import Path
import secrets
import sys
import winreg

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
from cbus_toolkit.toolkit_update_rollout_registry import inspect_rollout_owned_registry
from cbus_toolkit.windows_sesu_cohort_registry import WindowsSesuCohortRegistry


source = (root / "source.json").read_bytes()
node_id = json.loads(source)["data"][0]["nodeId"]
namespace = "sesu-native-" + secrets.token_hex(4)
registry = WindowsSesuCohortRegistry(namespace)
receipt = {
    "format": "cbus-sesu-owned-registry-native-system-v1",
    "context": "UTM guest agent LocalSystem HKCU; not interactive user",
    "source_sha256": hashlib.sha256(source).hexdigest(),
    "owned_key_path_sha256": hashlib.sha256(registry.path.encode()).hexdigest(),
    "branch_results": {},
    "original_updater_registry_accessed": False,
    "cleanup_confirmed": False,
}
result_path = root.parent / "cohort-native-result.json"


def decide(sample=None):
    return inspect_rollout_owned_registry(
        source, node_id=node_id, registry=registry, sample=sample,
    )


def set_owned(value, kind):
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, registry.path, 0,
        winreg.KEY_SET_VALUE | winreg.KEY_WOW64_32KEY,
    ) as handle:
        winreg.SetValueEx(handle, registry.entry, 0, kind, value)


try:
    absent = decide()
    assert absent.status == "failed"
    assert absent.registry_read.state == "key_absent"
    assert not absent.sample_attempted
    receipt["branch_results"]["key_absent"] = absent.status

    registry.ensure_owned_key()
    missing = decide(sample=lambda: 41)
    assert missing.status == "passed"
    assert missing.registry_read.state == "entry_absent"
    assert missing.cohort_generated and missing.cohort_persisted
    assert registry.read().value == "41"
    receipt["branch_results"]["entry_absent_seed"] = missing.status

    existing = decide(sample=lambda: (_ for _ in ()).throw(AssertionError("resampled")))
    assert existing.status == "passed" and not existing.sample_attempted
    assert existing.effective_cohort == 41
    receipt["branch_results"]["existing_reg_sz"] = existing.status

    set_owned("-1", winreg.REG_SZ)
    sentinel = decide(sample=lambda: 42)
    assert sentinel.status == "failed"
    assert sentinel.parse_status == "literal_minus_one_sentinel"
    assert sentinel.cohort_persisted and registry.read().value == "42"
    receipt["branch_results"]["literal_sentinel_seed"] = sentinel.status

    set_owned("bad", winreg.REG_SZ)
    malformed = decide()
    assert malformed.status == "failed" and not malformed.write_attempted
    receipt["branch_results"]["malformed_reg_sz"] = malformed.status

    set_owned(0xffffffff, winreg.REG_DWORD)
    high_bit = decide()
    assert high_bit.status == "unsupported" and not high_bit.write_attempted
    receipt["branch_results"]["high_bit_dword"] = high_bit.status
    receipt["status"] = "passed"
except Exception as error:
    receipt["status"] = "failed"
    receipt["error_type"] = type(error).__name__
    receipt["error_message"] = str(error)[:512]
finally:
    try:
        winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, registry.path,
                           winreg.KEY_WOW64_32KEY, 0)
        receipt["cleanup_confirmed"] = registry.read().state == "key_absent"
    except FileNotFoundError:
        receipt["cleanup_confirmed"] = registry.read().state == "key_absent"
    except Exception as error:
        receipt["cleanup_error_type"] = type(error).__name__
    if not receipt["cleanup_confirmed"]:
        receipt["status"] = "failed"
    result_path.write_text(json.dumps(receipt, sort_keys=True, indent=2), encoding="utf-8")

if receipt["status"] != "passed":
    raise SystemExit(1)
