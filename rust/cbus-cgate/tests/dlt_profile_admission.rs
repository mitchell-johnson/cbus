//! The Rust DLT/eDLT admission port reproduces every Python registry
//! decision and reason pinned by `research/export_dlt_admission.py`.

use cbus_cgate::dlt_profiles::refusal;
use serde_json::Value;

const VECTORS: &str = include_str!("../../testdata/vectors/dlt_profile_admission.jsonl");

#[test]
fn every_python_decision_and_reason_is_reproduced() {
    let mut admitted = 0;
    let mut count = 0;
    for line in VECTORS.lines().filter(|line| !line.trim().is_empty()) {
        let case: Value = serde_json::from_str(line).expect("vector JSON");
        let text = |name: &str| case[name].as_str();
        let got = refusal(
            text("workflow").expect("workflow"),
            text("unit_type").expect("unit type"),
            text("firmware"),
            text("catalog_number"),
        )
        .expect("known workflow");
        assert_eq!(got.as_deref(), text("reason"), "{line}");
        admitted += usize::from(got.is_none());
        count += 1;
    }
    assert!(count > 500, "vector count {count}");
    assert!(admitted > 40, "admitted count {admitted}");
}
