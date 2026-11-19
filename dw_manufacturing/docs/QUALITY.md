# Quality — نظام الجودة

Odoo Community has no Quality application, so the module ships a complete
lightweight one. Nothing here depends on Enterprise.

## 1. Templates

**Quality → Inspection Templates** (`dw.quality.template`)

| Field | Purpose |
|---|---|
| Product Family | Empty means the template applies to every family |
| Stage | Material Receipt · In Process · After Operation · Final Product · Before Delivery / Installation |
| Operation | Only for in-process and after-operation templates |
| Mandatory | A mandatory template blocks the manufacturing order until it passes |

Each template line is one test:

| Measure Type | Passes when |
|---|---|
| Numeric Measurement | The measured value is inside `[min, max]`, or within `target ± tolerance` when no range is given, or always when neither is set |
| Yes / No | The answer equals the expected answer |
| Choice | The answer is one of the comma separated allowed choices |
| Free Text | Any answer |

Per line: **Mandatory** (must be answered) and **Blocking** (a failure rejects
the product instead of asking for rework).

## 2. Checks

A check is created automatically for every matching template when the
manufacturing order is created, and can be regenerated with
**Manufacturing order → Fabrication Cost → Generate Quality Checks**.

Inspecting: fill the measured values, then **Validate**.

| Outcome | Condition | Release decision |
|---|---|---|
| Passed | Every test passes | Released |
| Needs Rework | Only non-blocking tests failed | On Hold |
| Rejected | A blocking test failed | Rejected |

A failure automatically opens a `dw.quality.issue` listing the failed tests,
with severity *major* for a rejection and *minor* for rework.

A validated check cannot be deleted.

## 3. The gate

`mrp.production.button_mark_done` is overridden. If any **mandatory** check has
not reached *Passed*, closing the order raises:

> Manufacturing order WH/MO/00012 cannot be closed: mandatory quality checks are
> not passed (QC/2026/00007).

The same rule applies to the manufacturing item: `Set Ready` refuses while a
mandatory check is open, and `Set Delivered` refuses on a rejected item and
raises a `rejected_delivery` alert.

The gate can be switched off per company:
**Settings → Metal Fabrication → Block manufacturing order on failed mandatory check**.

## 4. Corrective action and rework

On the check: corrective action text, action owner, rework cost, photos and
attachments.

On the issue: root cause, corrective action, responsible, deadline,
**Rework Required**, **Rework Cost**, and a close action.

A rework cost feeds the actual cost ledger as a `rework` line keyed
`rework:<issue id>`, so it is included in the manufacturing order cost and in
the profitability, and recomputation never duplicates it.

## 5. Suggested test sets

### Staircases
step height · step width · stair angle · frame straightness · weld quality ·
overall dimensions · handrail rigidity · paint quality

### Fences and handrails
post spacing · height · straightness · weld quality · fixing points ·
paint thickness · colour and finish

### Doors and gates
width · height · diagonals · opening and closing effort · locks and hinges ·
weld quality · paint quality · conformity to the drawing

## 6. Reporting

* **Quality → Quality Checks** — list and form
* **Quality → Quality Issues** — with rework cost totals
* **Reporting → Quality Analysis** — pivot of stage × result, rework cost measure
* **Reporting → Rework** — issues flagged as requiring rework
* **Print → Quality Inspection** — Arabic-capable PDF with every test, target,
  limits, measured value, deviation and result
