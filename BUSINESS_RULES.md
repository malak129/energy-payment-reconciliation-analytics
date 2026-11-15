# Business rules — design version 1

SYNTHETIC simulation, not certified accounting software, SAP or a bank integration.
These rules define the simulation's financial contract. Phase 3 implements
deterministic snapshot matching and controls; Phase 4 implements transactional
SQLite persistence, explicit operator effects and audit history.
Phase 2 authors synthetic examples and validates their explicit expected links
against these rules. It does not change the rules or execute reconciliation.
RECONCILIATION_ENGINE.md documents Phase 3's explicit matching, date/knowledge
assumptions, exception policy and conservative reversal holds. No original
financial sign convention or allocation invariant was changed.

Phase 4's physical constraints and snapshot membership are documented in
DATABASE_ARCHITECTURE.md. MANUAL_REVIEW_GUIDE.md defines the implemented workflow:
OPEN, IN_REVIEW, RESOLVED and REOPENED are live case states, independent of
source approval fixtures and payment settlement status. Accepted financial
operations atomically validate cash and receivable equations before moving the
current ledger head. Manual allocations require explicit targets and available
cash/debt; no candidate suggestion grants authority. Immutable decisions are
undone by linked releases or opposite corrections, never by editing source
amounts. Refunds and chargebacks are bank outflows and cannot be erased by undo.
Incompatible new-source replays are rejected without superseding accepted
manual decisions. Integer cents and the equations below remain unchanged.

## Statuses and legal transitions

Import rows are accepted (new valid original), duplicate (same identity and
canonical payload), rejected (invalid schema), or conflict (same identity,
different payload). These outcomes are immutable. Conflicts never overwrite.

Payment allocation status is derived at an as-of cutoff: unapplied (active
allocation=0 and available>0), partial (0<allocation<available), allocated
(allocation=available>0), reversed (available=0 after full outflow). Invoice
status is open (active allocation=0, adjusted face>0), partial
(0<allocation<adjusted face), settled (equal positive amounts), or cancelled
(adjusted face=0, allocation=0). Overdue is a separate due-date flag, not a
settlement state. Overpayment is residual cash and a review reason, never a
negative invoice balance. Review status is independent: pending or resolved
(a valid decision was atomically applied). A reason and candidates explain it.

Payment transitions: unapplied -> partial/allocated by allocation; partial ->
allocated by additional allocation; allocated -> partial/unapplied by release;
partial -> unapplied by release; any non-reversed state -> reversed only after
full linked cash outflow and required releases. Partial outflows may leave any
non-reversed status determined by balances. A reversed payment is terminal;
later incoming replacement cash is a new payment. Invoice open -> partial ->
settled through allocation (open -> settled allowed); releases can reopen it.
Authorized corrections may move an invoice between these states or cancelled,
provided constraints still hold. Cancelled may reopen with a positive correction.
Review pending -> resolved by decision, then a new case may be opened by new
evidence; never rewrite old cases. A running run ends completed or failed;
terminal runs cannot transition. Persist completed results atomically; failed
runs must not leave allocations. Reruns reference existing effects, not new cash.

## Matching and allocation invariants

An exact, normalized invoice reference is eligible only for a unique invoice,
same dataset/account/currency, valid dates, and positive open balance. Normalize
outer whitespace and case only; preserve leading zeros and internal punctuation.
Known account mismatches go to review. A missing claimed account may be inferred
only from a unique exact reference under the future rule's explicit policy.
Amounts alone or IBAN tokens never establish a match. Missing, unknown or
ambiguous references produce pending cases with candidates, without assignment.
Confidence is exact/manual, not an invented probability.

Single unambiguous references may allocate `min(available cash, open invoice)`;
short payments leave partial debt, excess stays unapplied and flagged. Explicit
combined references may allocate only if all targets are unique, same account,
and the amount equals the sum of their open balances; any mismatch or ambiguous
split goes to review with no partial auto-assignment. Duplicate normalized
references in source data are conflicts. Candidate matching never silently edits
input. A manual decision supplies explicit allocation amounts; an invalid
decision is rejected with no financial effects.

For every payment p: `available_p = received_p - linked_outflows_p >= 0`.
`active_alloc_p = sum(allocations_p) - sum(releases_p)` must be in
`[0, available_p]`. For each invoice i:
`adjusted_face_i = original_invoice_i + signed_corrections_i >= 0` and
`0 <= active_alloc_i <= adjusted_face_i`. Each allocation's cumulative releases
must not exceed its amount. Enforce dataset/account/currency consistency across
every link. Account consistency uses validated attribution, not an unverified
imported claim. No future-effective record affects an earlier cutoff. Financial
effects, decisions and audit events must commit in one transaction. Manual
approval does not waive balance constraints. A decision may be applied once;
reruns have stable effect IDs and cannot duplicate decisions or allocations.

## Refunds, chargebacks and corrections

Reversals are positive cash-outflow magnitudes linked to one original payment;
they are not additional negative payments, and are counted exactly once.
Cumulative reversals cannot exceed that payment. Refunds normally consume
unapplied cash first. Chargebacks also consume unapplied cash first in this
simulation. If outflows exceed unapplied cash, explicit allocation releases
must accompany them to reopen the affected invoices. If multiple allocations
could be released, route to review; never guess the invoice. Unlinked or
over-limit outflows remain quarantined outside the accepted ledger, with their
raw provenance preserved. Reversal and releases post atomically. Fee processing,
FX and reversing an outflow are out of scope; recovered cash is a new payment.

A Correction changes only a receivable (+ increases, - decreases), with actor,
reason, effective date and decision link. It never changes original invoice
amount, bank cash or import payload. Reduction below active allocations requires
explicit releases in the same transaction. Undo a correction with a new equal
opposite correction referencing it; undo once, without chains or cycles. Bank
data errors require a separately validated replacement event and documented
review procedure in a later phase, not an AR correction. Corrections are not
a general ledger or a substitute for legally issued credit notes.

## Duplicate handling and reproducible runs

File fingerprint: dataset + source system + SHA-256 bytes. Event identity:
dataset + source system + bank event ID, shared across payments and reversals.
Same key + same canonical payload is a duplicate and contributes zero new cash.
Same key + changed payload is a conflict; retain provenance and quarantine it.
Different event IDs with equal amounts/dates are distinct events, potentially
reviewable, never automatically deleted as duplicates. Every source row keeps
import ID, row number, payload hash, validation outcome and original record link.

Runs record input manifest hash, schema/rules/config versions, business as-of
date and known-at timestamp. Input snapshot includes applicable decisions and
corrections. Matching order is deterministic (booked date, payment ID, invoice ID).
Reruns reproduce decisions for the same snapshot without inserting effects twice.
Operational attempt IDs/timestamps may differ; result/input hashes must not.

## Month-end controls and KPI formulas

All equations use integer cents for accepted, EUR customer-ledger records known
to the run, with effective/booked date <= cutoff. Supplier invoices are separate.
Let I = original issued invoice totals, C = signed receivable corrections,
P = incoming payments, R = linked refunds, B = linked chargebacks,
A = allocations less releases. Then:

- Adjusted billed amount `G = I + C`.
- Payments received `P`; cash outflows `R + B`; net cash `N = P - R - B`.
- Active allocations `A`; unapplied cash `U = N - A`.
- Outstanding receivables `O = G - A`.
- Customer credit balance = sum of unapplied cash for identified accounts;
  suspense = unapplied cash for unidentified accounts; credit + suspense = U.
- Core controls: `N = A + U`, `G = A + O`, `G - N = O - U`.
- Settlement ratio = A/G when G>0; otherwise undefined, not a forced zero.
- Overdue receivables = sum of open balances where due_on < cutoff.

Compute bounds per invoice/payment first; aggregate equality alone can conceal
offsetting errors. Do not net receivables and credits across customers. Refunds
and chargebacks reduce cash; allocation releases reduce A, never cash a second
time. Corrections affect G, never P. Monthly movement controls are:
`closing O = opening O + issued invoices + corrections - allocation increases
+ releases`; `closing U = opening U + receipts - refunds - chargebacks
- allocation increases + releases`. Month flow KPIs use dates in that month;
closing balances are cumulative. Preserve historical snapshots; late/backdated
events require an explicitly restated run with a later known-at timestamp.

No opening migration balances, write-offs, interest, fees, direct debit mandate
management, bank clearing timing, tax certification or double-entry general
ledger are implemented. The controls reconcile this simulation's subledger only.

## Account attribution and decision effects

The imported payment account_id is a claim. Accepted exact-reference matching
validates that claim or derives an account from a unique invoice. An authorized
ManualDecision may carry resolved_account_id; its effects must belong to that
account. Original claims remain unchanged. Credit reporting uses the account
from accepted matching/decisions; absent validated attribution, residual cash is
suspense even if an unvalidated account_id was supplied. Later services must
reject a decision whose action is incompatible with its review subject (for
example an invoice correction case cannot allocate payment cash). Correction
review cases may target an invoice directly, without inventing a payment.

An accepted reversal on date d requires all mandatory releases effective on d;
neither reversals nor releases may precede the related payment/allocation.
Likewise allocations may not precede invoice issuance or payment booking.
Reject self-links/cycles and cross-dataset targets. These temporal/link checks
are dataset/engine responsibilities, not per-row validators. Phase 3 checks its
supported snapshot effects; Phase 4 additionally enforces transactional
atomicity, idempotency and explicit manual resolution in storage.
