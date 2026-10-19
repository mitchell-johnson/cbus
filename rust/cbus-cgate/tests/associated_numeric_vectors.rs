//! Wire/JSON regression for the associated numeric Level selector family
//! (issues #73 and #74). The live associated owner is covered by the
//! owning Service interaction tests; this pins the documented vector shape.
use serde_json::Value;

#[test]
fn associated_numeric_selector_vector_pins_documented_contract() {
    let text = include_str!("../../testdata/vectors/cgate_associated_numeric_selectors.json");
    let vector: Value = serde_json::from_str(text).expect("vector must parse");
    assert_eq!(
        vector["format"].as_str().unwrap(),
        "cbus-associated-numeric-selectors-v1"
    );
    assert_eq!(
        vector["original_contract"]["qualified_group_level_xml"]["count"]
            .as_u64()
            .unwrap(),
        10
    );
    assert_eq!(
        vector["original_contract"]["qualified_netvar_level_xml"]["count"]
            .as_u64()
            .unwrap(),
        4
    );
    assert_eq!(
        vector["original_contract"]["level_oid_xml"]["count"]
            .as_u64()
            .unwrap(),
        8
    );
    let copies = vector["copy_destinations"].as_array().unwrap();
    assert_eq!(copies.len(), 4);
    assert_eq!(copies[0]["status"].as_u64().unwrap(), 301);
    assert_eq!(copies[1]["status"].as_u64().unwrap(), 301);
    assert_eq!(copies[2]["status"].as_u64().unwrap(), 301);
    assert_eq!(copies[3]["status"].as_u64().unwrap(), 401);
    assert_eq!(
        copies[3]["final"].as_str().unwrap(),
        "401 Bad object or device ID: Associated Level destination not found"
    );
    let admitted = vector["load_preservation"]["admitted"].as_array().unwrap();
    assert_eq!(admitted.len(), 2);
    assert_eq!(
        admitted[0].as_str().unwrap(),
        "absent collection materializes one <TagsDLT/> and clears its marker on first LOAD"
    );
    assert_eq!(
        admitted[1].as_str().unwrap(),
        "strict-empty <TagsDLT/> deduplicates and clears its marker on first LOAD"
    );
    let unsupported = vector["load_preservation"]["unsupported_preserved_atomically"]
        .as_array()
        .unwrap();
    assert_eq!(unsupported.len(), 6);
    let level_xml = vector["level_xml"].as_array().unwrap();
    assert_eq!(level_xml.len(), 3);
    assert_eq!(level_xml[0]["status"].as_u64().unwrap(), 200);
    assert_eq!(level_xml[1]["status"].as_u64().unwrap(), 500);
    assert_eq!(level_xml[2]["status"].as_u64().unwrap(), 200);
    assert_eq!(
        vector["value_getter_precedence"]["status"]
            .as_u64()
            .unwrap(),
        401
    );
}

#[test]
fn associated_numeric_level_matrix_pins_eight_cells() {
    let text = include_str!("../../testdata/vectors/cgate_associated_numeric_level_matrix.jsonl");
    let rows: Vec<Value> = text
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| serde_json::from_str(line).expect("matrix row must parse"))
        .collect();
    assert_eq!(rows.len(), 8);
    let expected = [
        ("plain-group", "qualified", 200_u64, 344_u64, "<Level"),
        ("plain-group", "bare", 404_u64, 404_u64, "404"),
        ("completed-group", "qualified", 200_u64, 344_u64, "<Level"),
        ("completed-group", "bare", 404_u64, 404_u64, "404"),
        (
            "plain-netvar",
            "qualified",
            500_u64,
            500_u64,
            "500 Internal error.",
        ),
        ("plain-netvar", "bare", 404_u64, 404_u64, "404"),
        (
            "completed-netvar",
            "qualified",
            500_u64,
            500_u64,
            "500 Internal error.",
        ),
        ("completed-netvar", "bare", 404_u64, 404_u64, "404"),
    ];
    for (row, (owner, form, status, wire, body)) in rows.iter().zip(expected) {
        assert_eq!(
            row["format"].as_str().unwrap(),
            "cbus-associated-numeric-level-matrix-v1"
        );
        assert_eq!(row["issue"].as_u64().unwrap(), 73);
        assert_eq!(row["owner"].as_str().unwrap(), owner);
        assert_eq!(row["form"].as_str().unwrap(), form);
        assert_eq!(row["target"].as_str().unwrap(), "level");
        assert_eq!(row["status"].as_u64().unwrap(), status);
        assert_eq!(row["wire"].as_u64().unwrap(), wire);
        assert_eq!(row["body"].as_str().unwrap(), body);
    }
}

#[test]
fn associated_numeric_object_matrix_pins_observed_cells() {
    let text = include_str!(
        "../../testdata/vectors/cgate_associated_numeric_level_parent_object_matrix.jsonl"
    );
    let rows: Vec<Value> = text
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| serde_json::from_str(line).expect("matrix row must parse"))
        .collect();
    assert_eq!(rows.len(), 12);
    let expected = [
        ("plain-group", "qualified", 200_u64, 344_u64, "<Group"),
        ("plain-group", "bare", 404_u64, 404_u64, "404"),
        ("completed-group", "qualified", 200_u64, 344_u64, "<Group"),
        ("completed-group", "bare", 404_u64, 404_u64, "404"),
        ("plain-netvar", "qualified", 200_u64, 344_u64, "<NetVar"),
        ("plain-netvar", "bare", 404_u64, 404_u64, "404"),
        ("completed-netvar", "qualified", 200_u64, 344_u64, "<NetVar"),
        ("completed-netvar", "bare", 404_u64, 404_u64, "404"),
        (
            "plain-group",
            "qualified-lexical",
            200_u64,
            344_u64,
            "<Group",
        ),
        (
            "completed-group",
            "qualified-lexical",
            200_u64,
            344_u64,
            "<Group",
        ),
        (
            "plain-netvar",
            "qualified-lexical",
            200_u64,
            344_u64,
            "<NetVar",
        ),
        (
            "completed-netvar",
            "qualified-lexical",
            200_u64,
            344_u64,
            "<NetVar",
        ),
    ];
    for (row, (owner, form, status, wire, body)) in rows.iter().zip(expected) {
        assert_eq!(
            row["format"].as_str().unwrap(),
            "cbus-associated-numeric-level-object-matrix-v1"
        );
        assert_eq!(row["issue"].as_u64().unwrap(), 73);
        assert_eq!(row["target"].as_str().unwrap(), "object");
        assert!(row["observed_only"].as_bool().unwrap());
        assert_eq!(row["owner"].as_str().unwrap(), owner);
        assert_eq!(row["form"].as_str().unwrap(), form);
        assert_eq!(row["status"].as_u64().unwrap(), status);
        assert_eq!(row["wire"].as_u64().unwrap(), wire);
        assert_eq!(row["body"].as_str().unwrap(), body);
    }
}

#[test]
fn ordinary_numeric_level_value_pins_typed_owner_contract() {
    let text = include_str!("../../testdata/vectors/cgate_ordinary_numeric_level_value.jsonl");
    let rows: Vec<Value> = text
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| serde_json::from_str(line).expect("ordinary row must parse"))
        .collect();
    assert_eq!(rows.len(), 13);
    for row in &rows {
        assert_eq!(
            row["format"].as_str().unwrap(),
            "cbus-ordinary-numeric-level-value-v1"
        );
        assert_eq!(row["issue"].as_u64().unwrap(), 131);
        assert!(matches!(row["target"].as_str().unwrap(), "value" | "xml"));
    }
    let by_request = |request: &str| {
        rows.iter()
            .find(|row| row["request"].as_str().unwrap() == request)
            .unwrap_or_else(|| panic!("missing ordinary vector row {request}"))
    };
    assert_eq!(
        by_request("DBSETSAFE //T131/254/80/8/4/Value 99")["status"]
            .as_u64()
            .unwrap(),
        200
    );
    assert_eq!(
        by_request("DBSETSAFE //T131/254/80/8/4/Value oops")["status"]
            .as_u64()
            .unwrap(),
        400
    );
    assert_eq!(
        by_request("DBSET //T131/254/80/8/4/Value oops")["status"]
            .as_u64()
            .unwrap(),
        408
    );
    assert_eq!(
        by_request("DBSETSAFE //T131/254/80/8/9/Value 99")["status"]
            .as_u64()
            .unwrap(),
        401
    );
    assert_eq!(
        by_request("DBSETSAFE //OTHER/254/80/8/4/Value 99")["status"]
            .as_u64()
            .unwrap(),
        404
    );
    assert_eq!(
        by_request("DBSETSAFE //T131/254/81/8/4/Value 99")["status"]
            .as_u64()
            .unwrap(),
        200
    );
}

#[test]
fn associated_numeric_copy_pins_canonical_destinations() {
    let text = include_str!("../../testdata/vectors/cgate_associated_numeric_copy.jsonl");
    let rows: Vec<Value> = text
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| serde_json::from_str(line).expect("copy row must parse"))
        .collect();
    assert_eq!(rows.len(), 8);
    let expected = [
        (
            "DBCOPYSAFE !<source-Level-OID> //LAB/11/56/1 12 NumericCopy",
            301_u64,
        ),
        ("DBCOPY !<source-Level-OID> //LAB/11/56/1", 301_u64),
        (
            "DBCOPYSAFE //LAB/Renamed/56/1/9 //LAB/11/56/1 13 NumericLexicalCopy",
            301_u64,
        ),
        (
            "DBCOPYSAFE !<netvar-Level-OID> //LAB/11/56/4 43 NetVarNumericCopy",
            301_u64,
        ),
        (
            "DBCOPYSAFE !<source-Level-OID> //LAB/Renamed/56/1 14 LexicalCopy",
            301_u64,
        ),
        (
            "DBCOPYSAFE !<source-Level-OID> //LAB/11/56/9 15 Ghost",
            401_u64,
        ),
        (
            "DBCOPYSAFE !<source-Level-OID> //LAB/11/99 15 Ghost",
            401_u64,
        ),
        (
            "DBCOPYSAFE !<raw-Level-OID> //LAB/11/56/1 16 RawCopy",
            408_u64,
        ),
    ];
    for (row, (request, status)) in rows.iter().zip(expected) {
        assert_eq!(
            row["format"].as_str().unwrap(),
            "cbus-associated-numeric-copy-v1"
        );
        assert_eq!(row["issue"].as_u64().unwrap(), 74);
        assert_eq!(row["target"].as_str().unwrap(), "copy");
        assert_eq!(row["request"].as_str().unwrap(), request);
        assert_eq!(row["status"].as_u64().unwrap(), status);
        assert_eq!(row["wire"].as_u64().unwrap(), status);
    }
}
