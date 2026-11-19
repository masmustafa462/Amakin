# Actual Costing — حساب التكلفة الفعلية

## 1. Where the numbers come from

Every actual cost of a manufacturing order is one row in
`dw.production.cost.line`. Nothing is estimated, nothing is guessed.

| Cost type | Source | Deterministic key |
|---|---|---|
| Raw material | Each **done** raw `stock.move` of the order | `move:<id>` |
| Non recoverable scrap | Each **done** `stock.scrap` of the order | `scrap:<id>` |
| Labour | Each `mrp.workcenter.productivity` entry of every work order | `wo_time:<id>` |
| Labour (unlogged) | The part of `workorder.duration` not covered by time entries | `wo_labor:<workorder id>` |
| Machine | `workorder.duration × work center cost per hour` | `wo_machine:<workorder id>` |
| Transport / installation / contractor / outsourcing / direct | Each **approved** `dw.project.cost.entry` | `expense:<id>` |
| Rework | Each `dw.quality.issue` with a rework cost | `rework:<id>` |
| Overhead | The matching `dw.overhead.rule` | `overhead:<rule id>` |

---

## 2. Material cost is real inventory valuation

> **Important Odoo 19 change.** `stock.valuation.layer` **no longer exists**.
> Odoo 19 stores the valued amount directly on the stock move
> (`stock.move.value`, with `is_in` / `is_out` / `is_valued`), and manual
> valuation corrections are kept in the `product.value` model.

The engine therefore reads `move.value` — the amount Odoo itself posted — and
only falls back to `standard_price × quantity` when the move carries no
valuation at all (a non-valued location pair, for example).

This means the cost automatically follows the product's costing method:

* **Standard** → the standard price at the time of the move
* **Average** → the running average
* **FIFO** → the actual layers consumed

There is a test that receives 10 units at 10 and 10 units at 20 on a FIFO
product, consumes 15, and asserts the cost is **200**, not
`15 × standard_price` (`test_02_fifo_valuation_is_used_not_standard_price`).

### Returns and negative consumption
The sign follows the move direction: a move whose destination is the production
location is a consumption (positive), any other direction is a return
(negative). The quantity and weight on the cost line carry the same sign, so a
return reduces both the cost and the issued weight.

### Customer supplied material
A product flagged **Supplied by Customer** is consumed and tracked by weight but
its cost line is written with an amount of zero, so it never inflates the
project cost.

---

## 3. Labour and machine

Labour uses `dw.labor.rate`. The most specific valid rate wins, scored as:

| Match | Score |
|---|---|
| user / employee | +8 |
| work center | +4 |
| operation type | +2 |

A rate that names a user, work center or operation the current record does not
match is discarded entirely. A rate with none of them set is the company
fallback. Validity is filtered by `date_start` / `date_end`.

Machine cost uses the work center's own `Cost per hour`.

> If your work center rate already includes the operator, enable
> **Settings → Metal Fabrication → Work center rate includes labour**. The
> engine then stops writing machine lines and only the labour rate applies, so
> nothing is counted twice.

---

## 4. Scrap and double counting

Scrap taken **from stock** (`location_id.usage == 'internal'`) is material that
was never in a raw move, so it is charged at its valued amount.

Scrap taken **from the production location** is work in progress that was
already consumed by a raw move. Charging it again would double count, so the
line is written with **amount 0** and a note, while still recording the quantity
and the weight for the scrap reports. This is asserted by
`test_08_scrap_from_stock_adds_cost_scrap_from_wip_does_not`.

---

## 5. Idempotency — no duplicated cost lines

`_dw_recompute_actual_cost()` is safe to run any number of times, from the
button, from `button_mark_done`, from a scrap validation, from an expense
approval or from a cron.

How it is guaranteed:

1. Every automatic line carries a **deterministic `source_key`** derived from
   the source record's id.
2. A partial unique index enforces it at database level:
   ```sql
   UNIQUE (company_id, source_key) WHERE source_key IS NOT NULL AND is_automatic IS TRUE
   ```
3. The engine builds the target set, then **updates existing rows by key and
   creates only the missing ones**. Automatic lines whose source has
   disappeared are removed.

`test_05_recompute_is_idempotent` runs the engine five times and asserts the
line count, the total and the uniqueness of every key are unchanged.
`test_13_unique_source_key_constraint` asserts the database itself rejects a
duplicate.

---

## 6. Approved lines are protected

| Line state | On recomputation |
|---|---|
| draft / confirmed | Overwritten with the new value |
| **approved** | The amount is **kept**. A `dw.production.cost.revision` row records the old value, the computed value, the user, the date and the reason |
| approved, source gone | Kept, with a revision noting the source no longer exists |

Setting **Settings → Allow updating approved cost lines** lets the engine write
the new amount, but the audit revision is still written first.

Approved lines cannot be deleted (`UserError`), and the revision log itself can
never be deleted. Historical approved costs are therefore permanent.

---

## 7. Overhead

`dw.overhead.rule` supports nine absorption methods: percentage of material,
labour, direct cost or manufacturing order value; amount per hour, per kilogram,
per unit, per m²; and a fixed amount. The most specific valid rule wins
(family first, then the company-wide rule), filtered by validity dates.

Overhead is computed **last**, from the other buckets of the same run, so it
never feeds on itself.

---

## 8. Running the engine

* Automatically when a manufacturing order is marked done
* Automatically when a scrap is validated or an expense is approved or cancelled
* **Manufacturing order → Fabrication Cost → Recompute Actual Cost**
* **Manufacturing item → Recompute Actual Cost**
* From code: `production._dw_recompute_actual_cost()`

`Last Cost Run` on the manufacturing order shows when it last executed.

---

## 9. Reading the result

| Where | What |
|---|---|
| Manufacturing order → *Fabrication Cost* tab | Buckets, estimate, variance, time and weight comparison, full line list |
| Manufacturing item → *Actual Cost* tab | Same buckets rolled up to the item, plus revenue and margin |
| Costing → Actual Cost Lines | The whole ledger with pivot and graph |
| Reporting → Cost and Time Variance | One row per manufacturing order |
| Print → Cost Card | Arabic-capable PDF cost card |
