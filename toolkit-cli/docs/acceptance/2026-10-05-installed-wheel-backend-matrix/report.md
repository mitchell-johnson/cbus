# Complete installed-wheel backend plans

The installed-wheel interoperability job previously ran both backends within one job. Its mock phase hit the 7,200-second command limit before producing a terminal result, so the daemon phase never started. The revised CI workflow runs the complete mock and daemon declarations in separate jobs, then requires a combined audit of both retained results.

## Preserved scope

This revision declares **498 mock and 509 daemon explicit IDs, 1,007 combined**, plus **seven whole core modules**. These are this branch's declarations; the separately developed Application database branch has a larger roster. No explicit ID or whole module was removed. Omitting the new `--backend` option preserves the original complete two-backend behavior. `--backend mock|daemon` chooses exactly the corresponding full Make declaration and is mutually exclusive with focused `--select` requests.

Each CI child builds the owned servers and installs a fresh wheel. Jobs use `fail-fast: false`, separate outputs and always-uploaded artifacts, a provisional 14,400-second command limit and a 300-minute job ceiling. The new budget has not yet been demonstrated sufficient by a completed hosted run.

The aggregate job retains the previous required-check name. It requires both jobs to succeed, re-audits their collection/JUnit/trace records, verifies all required bodies and the bounded optional skip policy, and compares source revision, Git-tracked/nonignored source maps and product payload maps. It binds the per-job origin audits and exact guard artifact files; it does not independently recreate the original installed environments or reinterpret their origin streams. Executable identities remain separately pinned. Two process epochs are not concatenated into one test run.

## Actual local checks

These are separate narrow epochs, not a full installed-wheel gate:

- Runner and matrix helpers: **138 passing parents**, no failures/skips/subtests. This includes 94 inherited and 44 new cases.
- Serial recovery fixture: **4 passing parents and 7 separately reported passing subtests**, with pytest and maintained audit exit 0.
- Freshness and registration checks after regeneration: **17 passing parents and 6 separately reported passing subtests**, with pytest and maintained audit exit 0.
- Both fresh debug-server builds passed. All **18** actual owned capture, sanitizer, generation and reproduction commands passed. Only the declared outputs changed; six source-closure maps, the selected executables and eight protected native/pre-fix files stayed exact.

The serial proof's private wrapper initially expected the parent count to equal the aggregate count and exited 1 after the passing pytest/auditor commands. Its failed wrapper receipt is retained; the corrected artifact-only readback distinguishes four parents from seven subtests and does not replay the product test.

This evidence documentation was added after these checks. The tested source files remain byte-exact; documentation additions do not turn a narrow pass into a full-suite claim.

## Retained hosted failures

[Run 37210167852](https://github.com/mitchell-johnson/cbus/actions/runs/37210167852), whose PR/run head is `6807786f5082c3a6b3c87f1da2662ab588bafde6`, remains historical failed evidence. The retained installed-wheel artifact records checkout/source revision `a0c471131572c81888cc4c8bdd4c8ee4bec956aa`; the PR head is not a claim that this exact checkout was executed.

Its installed-wheel artifact, ID **11308443540**, is 205,853,555 bytes with SHA-256 `fa236beb559e3e49a7884d7d0428454c56333fdb8bd0c752137015e34be65f17`. The mock collected 518 parent cases and emitted 359 pass progress markers plus one skip marker before timeout. Its last child started about eight seconds before the deadline; completed Python child lifetimes totaled about 6,789 seconds. This supports an aggregate budget cutoff. Progress markers are not terminal acceptance; no daemon phase ran.

The source artifact, ID **11309443598**, is 2,185,985 bytes with SHA-256 `1ae8346af2dd9f1be5ab854419f92369738fc1408bec96c39a4d53e959ba8944`. Its offline roster had 10,551 passing parents, one failure and 1,501 provisioning skips, plus 44,906 passing subtests. The failed uncertain-send recovery fixture did not raise its expected exception. One isolated rerun of that original fixture passed, so its hosted cause remains unproven. The fixture now places its malformed bytes before the unchanged valid reply, preserving the actual simulated move, uncertain journal, fresh read-only verification and no-replay checks; the local four-parent proof above covers this proposal.

Both later source interoperability phases passed their maintained audits: mock **517 passing parents, one admitted provisioning skip and 158 passing subtests**; daemon **660 passing parents, one admitted provisioning skip and 69 passing subtests**. These source runs do not replace the installed-wheel gate.

## Remaining acceptance

[Issue 128](https://github.com/mitchell-johnson/cbus/issues/128) remains open until the revised full hosted backend matrix and aggregate gate actually pass. No native application, hardware, broad Toolkit parity or global feature-completeness credit is granted here. Historical receipts are preserved; new owned captures do not relabel an original server execution.
