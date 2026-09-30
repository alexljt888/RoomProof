# Backend domain foundation

Python 3.11+ and the standard library only. From the repository root:

```sh
python3 -m unittest discover -s backend/tests -v
```

`app/domain.py` defines inspections with embedded property details and renter
names, rooms, registered photo metadata, analyses, and findings. Parent object
references enforce ownership; ID properties expose these relationships. Inverse
collections and persistence are left to the future repository/service layer.
The domain does not import `ml/`.

AI proposes; the renter confirms. Every finding starts `pending_review`, even
with clear AI certainty. `confirm(reportable=...)` copies the original proposal;
`edit_and_confirm(ApprovedContent(...))` records human replacement content;
`reject(reason)` records rejection without approved content. The latter two
confirmation actions both lead to `confirmed`; editing is an action, not a state.
A completed review cannot be repeated. Only confirmed findings with approved
`reportable=True` are eligible for eventual report inclusion. Eligibility does
not prove image availability and does not generate a report.

Original proposals, evidence references, and approved review snapshots are frozen.
Dataclasses prevent normal attribute assignment; the two controlled terminal
transitions internally replace a private result/review exactly once. This is
practical immutability, not protection against deliberate Python reflection.
Future services must enforce human authorization; future repositories must make
transitions atomic across concurrent requests. Renter names are not authentication.

Photo metadata accepts a basename and declared image media type, not bytes, paths,
or URLs. It does not verify an upload or media contents. Capture surface hints
are optional and do not constrain AI classification. Original `FindingProposal.evidence_photos` must include the analyzed photo.
`ApprovedContent.evidence_photos` records the human-approved selection and may
instead contain other photos. Both selections must be nonempty, unique, and
belong to the finding's room and inspection. Confirm-original copies original
evidence. Edit-and-confirm requires a complete `ApprovedContent`, including an
explicit evidence selection; pass `finding.original_proposal.evidence_photos`
when retaining it. There is no nullable or implicit replacement selection.
Original evidence and analysis provenance remain unchanged after review. Neither
selection implies durable or tamper-proof storage.

Evidence and limitations accept lists or tuples, copy them into tuples, and
reject invalid containers/members with `InvalidDomainData`. Once reviewed, public
review methods check state before validating a new payload and raise
`TransitionConflict` for subsequent attempts.

An analysis completes with `findings_present`, `no_visible_findings`, or
`uncertain`, or fails with a safe enumerated code. Only successful analyses whose
outcome permits findings can be their source. Services will later assemble the
analysis and findings consistently; no analyzer runs here. Raw provider errors
must not be stored as failure information.

`InvalidDomainData` identifies invalid values/relationships (future HTTP 422);
`TransitionConflict` identifies repeated terminal operations (future HTTP 409).
No API, storage, analyzer, repository, authentication, or report implementation is
included. Backend surface/category vocabulary is intentionally independent of ML.
