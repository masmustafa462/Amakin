# Profitability — تقارير الربحية

## 1. What counts as revenue

| Situation | Actual revenue |
|---|---|
| Quotation, not confirmed | **0** — only *Expected Revenue* is shown |
| Invoice in draft | **0** |
| Customer invoice posted | `+ price_subtotal` of the invoice lines linked to the item's sales order line |
| Credit note posted | `− price_subtotal` |
| Work for the main company, **same legal entity** | **0** accounting revenue. An *Internal Transfer Value* is reported instead |
| Work for the main company, **separate legal entity** | Treated like any external customer: real invoices, real revenue |

The rule is enforced in `dw.opening._compute_revenue`, and there are tests for
each case: `test_01_quotation_is_not_revenue`,
`test_02_only_posted_invoices_count`, `test_03_credit_note_reduces_revenue`,
`test_04_internal_work_produces_no_accounting_revenue`,
`test_05_separate_legal_entity_behaves_like_a_customer`.

### Tax
Revenue is taken from `price_subtotal`, that is **excluding tax**, which is the
correct basis for margin analysis. **Settings → Report revenue including tax**
records the company policy for reports that need the inclusive figure.

### Internal transfer value
For same-entity work no accounting revenue exists — inventing one would create
fictitious income. The module reports the agreed management value separately,
under its own label *Internal Transfer Value / قيمة التحويل الداخلي*, on the
item, the sales order, the project and the analysis view. Profit for that work
is measured against this value.

---

## 2. What counts as cost

Item and manufacturing order cost comes from the actual cost ledger
(`ACTUAL_COSTING.md`).

Project cost adds standalone `dw.project.cost.entry` records that are approved
but attached to the project rather than to a manufacturing order — site rental,
supervision, mobilisation.

---

## 3. Levels

| Level | Where |
|---|---|
| Manufacturing item | Item form → *Actual Cost* tab |
| Manufacturing order | MO → *Fabrication Cost* tab |
| Sales order | SO → *Manufacturing Items* tab footer |
| Project | Project → *Fabrication Profitability* tab |
| Customer | Reporting → Customer Profitability |
| Product family | Reporting → group by Product Family |
| Period | Any pivot, group by Month |
| Company / branch | Standard multi-company filter |

---

## 4. The analysis views

### `dw.profitability.report`
A read-only SQL view, one row per manufacturing item, carrying every dimension
(project, sales order, customer, family, product, manufacturing order,
relationship, date) and every measure:

expected revenue · invoiced revenue · actual revenue · internal transfer value ·
estimated cost · actual cost · cost variance · expected profit · actual profit ·
**cost per kg** · **cost per m²** · **cost per linear meter**.

Filters: Over Budget, Loss Making, Internal Work.
Group by: project, customer, family, sales order, manufacturing order, month.

### `dw.cost.variance.report`
One row per manufacturing order: estimated vs actual total, material variance,
labour variance, planned vs actual minutes, planned vs issued vs scrap weight.
Filters: Over Budget, Late.

Both are database views, so they never duplicate data and are always current.

---

## 5. Project figures

| Field | Meaning |
|---|---|
| Expected Revenue | Σ item expected revenue |
| Invoiced Revenue | Σ posted invoices minus credit notes |
| Internal Transfer Value | Σ management transfer values |
| Estimated Cost | Σ item estimated cost |
| Actual Cost | Σ item actual cost + approved standalone project expenses |
| Expected / Actual Profit | Revenue minus cost |
| Expected / Actual Margin % | Profit ÷ revenue |
| Cost Variance | Actual − estimated |
| Revenue Variance | Actual − expected |
| Completion % | Items ready or delivered ÷ total items |
| Work in Progress Value | Accumulated actual cost while items are still in production |

---

## 6. PDF reports

| Report | Model |
|---|---|
| Project Profitability | `project.project` |
| Manufacturing Order Cost Card | `mrp.production` |
| Cost Variance | `mrp.production` |
| Scrap Report | `mrp.production` |
| Quality Inspection | `dw.quality.check` |
| Manufacturing Item | `dw.opening` |

All six switch to right-to-left automatically when printed in Arabic.

---

## 7. Access

Profit and margin figures are visible only to the
**Fabrication Profitability Access** group (implied by the Fabrication Manager).
See `SECURITY.md`.
