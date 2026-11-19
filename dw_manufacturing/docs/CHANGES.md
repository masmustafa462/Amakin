# Phase 2 — Files, Decisions and Limitations

## 1. Version

`19.0.1.0.4` → **`19.0.2.0.0`**
Display name: `Door and Window Manufacturing` → **`Metal Fabrication Management` / `إدارة التصنيع المعدني`**
Technical name unchanged: **`dw_manufacturing`**

---

## 2. Files modified from phase 1

| File | Change |
|---|---|
| `__init__.py` | Added the `report` package |
| `__manifest__.py` | New name, summary, description, version `19.0.2.0.0`, added `stock_account` and `account` to `depends`, 33 data files, report asset bundle |
| `models/__init__.py` | 15 model modules instead of 4 |
| `models/dw_opening.py` | Rewritten and generalised. **Every phase-1 field kept**; ~70 fields added |
| `models/dw_component_rule.py` | Rewritten. **Every phase-1 field kept**; guided formulas, conditions, post processing added |
| `models/mrp_production.py` | Kept the three `dw_*` links; added the actual costing engine, the quality gate, `mrp.workorder` and `mrp.bom` extensions |
| `models/sale_order.py` | Kept every phase-1 field; added roll-up totals and the `project.project` profitability extension |
| `security/dw_security.xml` | 2 groups → 8. `group_dw_user` and `group_dw_manager` keep their XML ids |
| `security/ir.model.access.csv` | 6 rules → 85 |
| `data/dw_sequence.xml` | 1 sequence → 4 |
| `views/dw_opening_views.xml` | Rewritten: family-driven dimension visibility, 9 notebook pages, kanban, pivot, graph |
| `views/dw_component_rule_views.xml` | Rewritten for the formula builder |
| `views/sale_order_views.xml` | Extended with totals and the MO creation button |
| `views/mrp_production_views.xml` | Extended with the cost and quality pages |
| `views/dw_menus.xml` | 5 menu items → 34 |
| `i18n/ar.po` | 1 entry → **1096 entries, 100 % translated** |

## 3. Files added

**Models (11 new files)**
`dw_config.py` · `dw_metal_profile.py` · `dw_product_family.py` · `dw_drawing.py` ·
`dw_quality.py` · `dw_labor_rate.py` · `dw_production_cost.py` · `dw_scrap.py` ·
`dw_alert.py` · `dw_alert_scan.py` · `res_company.py`

**Report (9 files)**
`report/__init__.py` · `dw_analysis.py` (2 SQL views) · `dw_analysis_views.xml` ·
`dw_report_paperformat.xml` · `dw_report_layout.xml` · `dw_report_actions.xml` ·
`dw_item_report.xml` · `dw_production_cost_report.xml` (cost card, variance, scrap) ·
`dw_project_profitability_report.xml` · `dw_quality_report.xml`

**Security** `security/dw_record_rules.xml`

**Data** `dw_dimension_data.xml` · `dw_metal_data.xml` · `dw_operation_data.xml` · `dw_cron.xml`

**Views (11 new files)**
`dw_config_views.xml` · `dw_metal_profile_views.xml` · `dw_product_family_views.xml` ·
`dw_drawing_views.xml` · `dw_quality_views.xml` · `dw_scrap_views.xml` ·
`dw_labor_rate_views.xml` · `dw_production_cost_views.xml` · `dw_alert_views.xml` ·
`product_views.xml` · `project_views.xml` · `mrp_bom_views.xml` ·
`res_config_settings_views.xml`

**Static** `static/description/icon.png` · `static/src/scss/dw_report_arabic.scss` ·
`static/src/fonts/Amiri-Regular.ttf` · `Amiri-Bold.ttf` · `AMIRI-LICENSE.txt`

**Tests (8 files, 79 tests)** and **docs (10 files)**.

Totals: 7 778 lines of Python, 4 593 lines of XML.

## 4. New models

| Model | Purpose |
|---|---|
| `dw.dimension.field` | Catalogue of measurable attributes |
| `dw.metal.type` / `dw.metal.grade` | Metals and grades with densities |
| `dw.finish.type` | Paint, powder, galvanizing, polish, raw |
| `dw.operation.type` | Fabrication operations with duration modes |
| `dw.metal.profile` | Section geometry and theoretical weight |
| `dw.product.family` (+ `.operation`) | The configuration hub |
| `dw.component.rule.term` / `.condition` | Guided formulas and gating conditions |
| `dw.opening.operation` / `.extra.cost` | Planned operations and manual estimate items |
| `dw.drawing` / `dw.drawing.revision` | Drawing revision control |
| `dw.quality.template` (+ `.line`), `dw.quality.check` (+ `.line`), `dw.quality.issue` | Quality |
| `dw.labor.rate` | Hourly labour rates |
| `dw.overhead.rule` | Overhead absorption |
| `dw.production.cost.line` / `.revision` | Actual cost ledger and audit log |
| `dw.project.cost.entry` | Site expenses |
| `dw.scrap.reason` / `dw.material.offcut` | Scrap classification and remnants |
| `dw.alert.rule` / `dw.alert` | Alerts |
| `dw.profitability.report` / `dw.cost.variance.report` | Read-only SQL views |

Extended: `product.template`, `product.product`, `stock.scrap`, `stock.move`,
`mrp.production`, `mrp.workorder`, `mrp.bom`, `sale.order`, `sale.order.line`,
`project.project`, `res.company`, `res.config.settings`.

---

## 5. Technical decisions where the requirement met Odoo 19 Community

### 5.1 `stock.valuation.layer` no longer exists
**Requirement:** read actual material cost from `stock.valuation.layer`.
**Reality:** Odoo 19 removed that model. Inventory valuation now lives on
`stock.move.value` (with `is_in` / `is_out` / `is_valued`), and manual valuation
corrections are stored in the new `product.value` model.
**Decision:** the engine reads `move.value` — the amount Odoo itself posted —
and only falls back to `standard_price × quantity` when a move carries no
valuation at all. This satisfies the intent exactly: standard, average and FIFO
costing are all honoured. `dw.production.cost.line.product_value_id` links to
`product.value` when a manual correction exists.

### 5.2 No Quality application in Community
**Decision:** a self-contained quality subsystem
(`dw.quality.template` / `.check` / `.issue`) with a hard gate on
`button_mark_done`. No Enterprise dependency.

### 5.3 Odoo 19 already ships `stock.scrap.reason.tag`
**Decision:** keep `dw.scrap.reason` as required. The standard tag stays a free
label; `dw.scrap.reason` carries the fabrication behaviour the costing and alert
engines need (planned, reusable, approval, default owner). They coexist.

### 5.4 Virtual production locations have no fixed XML id
`stock.location_production` does not exist in Odoo 19; production locations are
created per company. The module resolves them the same way `mrp` does — by
`usage = 'production'` and company, preferring `production.production_location_id`.

### 5.5 Operator precedence in guided formulas
Supporting full precedence would require parsing an expression, which is exactly
what the requirement forbids. **Decision:** strict left-to-right evaluation of an
ordered term list, with a live **Formula Preview** so the result is never
ambiguous. Documented and covered by a test.

### 5.6 `groups_id` → `group_ids`, `attrs` removed, `tree` → `list`
Odoo 19 renamed several fields and dropped legacy view syntax. All views and
data files use the current syntax; `models.Constraint`, `models.UniqueIndex` and
`aggregator` replace `_sql_constraints` and `group_operator`.

### 5.7 Scrap taken from work in progress
Charging it again would double count material already consumed by a raw move.
**Decision:** record the line with amount 0 and a note, but keep quantity and
weight so the scrap reports stay complete.

### 5.8 Component quantity precision
Component quantities are stored with 6 decimals rather than the standard
*Product Unit* precision (2), because 5.9136 m of sheet is a meaningful
difference in fabrication. Bill of materials lines still follow Odoo's own
precision.

---

## 6. Known limitations and deferred items

| # | Item | Status and reason |
|---|---|---|
| 1 | Page header and footer in PDF | Requires the Odoo-patched wkhtmltopdf. The container used for testing has the distribution build, so headers were skipped there. The report body, RTL and Arabic font are unaffected. |
| 2 | Inter-company sale/purchase automation | The module fully supports the *separate legal entity* relationship and reports it correctly, but does not generate the mirrored purchase order. Odoo's standard inter-company rules can be configured alongside. |
| 3 | QR code on off-cut labels | Every off-cut carries a unique barcode. A dedicated label PDF is not shipped; use Odoo's barcode controller (`/report/barcode/QR/<barcode>`) or any label template. |
| 4 | Cash collection ("الإيراد المحصل") | Reported as invoiced revenue. Collected cash would need `account.payment` reconciliation analysis, which is outside the phase-2 scope; the field is not shown rather than shown wrong. |
| 5 | Work in progress valuation | Reported as accumulated actual cost while items are in production. A full WIP account posting would require a costing journal, which was not requested. |
| 6 | Automatic nesting / cutting optimisation | Off-cuts are recorded and reusable, but the module does not run a nesting algorithm to choose which remnant to cut from. |
| 7 | Demo data | No demo data is shipped, so installing on a production database adds nothing but configuration catalogues. The test suite builds its own fixtures. |
| 8 | Alert notifications | Alerts are records plus a scheduled scanner (disabled by default). E-mail or Slack push is not wired. |

---

## 7. Acceptance criteria — status

| # | Criterion | Status |
|---|---|---|
| 1 | Installs on a new Odoo 19 Community database without errors | ✅ verified, exit 0, no warnings |
| 2 | Upgrades the existing module without losing phase-1 data | ✅ verified with a real phase-1 dump |
| 3 | Supports doors, windows, fences, handrails, staircases, gates | ✅ plus facades, canopies, structures, shelving, sheet metal, custom |
| 4 | A new product family can be added without code | ✅ scenario 4 |
| 5 | Quotation, BoM and MO from a manufacturing item | ✅ scenarios 1–4 |
| 6 | Actual cost from real consumption | ✅ from `stock.move.value`, FIFO test included |
| 7 | Labour and machine from actual time | ✅ |
| 8 | Scrap and reusable off-cuts recorded | ✅ with standard stock moves |
| 9 | Quality checks and rework | ✅ with a hard gate |
| 10 | Project profitability from real revenue and cost | ✅ posted invoices and credit notes only |
| 11 | Menus and reports display correctly in Arabic | ✅ 1111/1111 terms |
| 12 | Arabic PDF without separated letters or RTL problems | ✅ inspected on a rendered page |
| 13 | No duplicated cost lines on recomputation | ✅ unique index + 5-run test |
| 14 | The three main scenarios and the new-product scenario pass | ✅ 4/4 |
| 15 | No Enterprise dependency | ✅ `depends` lists Community modules only |

---

## 8. Fix — a family saved without dimensions or rules (2026-09-06)

Reported from the field: a family created with only a name and a kind
("باب 6*7") produced a manufacturing item whose Dimensions section was empty,
so nothing could be entered and the item could not move forward.

Cause: the item form shows exactly the dimensions the family selects. With no
dimension selected, every input was hidden and `Generate Components` raised a
hard error with no way out.

What changed:

| File | Change |
|---|---|
| `models/dw_product_family.py` | `DIMENSION_PRESETS` — a standard dimension set for each of the 13 product kinds, plus a generic set for *custom* and *other*. New `uses_default_dimensions` flag and `action_apply_default_dimensions()`. |
| `models/dw_opening.py` | `visible_dimension_codes` now falls back to the preset of the family's product kind, computed live so an upgraded family with a stale cache is also covered. New `setup_warning` naming exactly what is missing. `action_generate_components` succeeds when the components were entered by hand, and otherwise raises an error that says what to do. |
| `views/dw_opening_views.xml` | Warning banner on draft and quoted items. |
| `views/dw_product_family_views.xml` | Warning banner with an *Apply the standard dimensions* button, a second button in the Dimensions tab, and the flag in the list view. |
| `tests/test_rule_engine.py` | `TestFamilyWithoutConfiguration` — 6 tests covering exactly this situation. |
| `i18n/ar.po` | 14 new terms translated; 1110/1110. |

Verified on a live database by recreating the reported record, including a
family whose stored dimension cache was forced empty: the six door dimensions
appear, width and height accept values, and the error message names the family
and the two ways out.

---

## 9. Fix — the quotation flag no longer blocks the stage flow (2026-09-06)

`dw_is_manufacturing_quote` on the sales order was a plain checkbox with no
default. An item could be synced onto a quotation, reach *Quoted*, and then
stay there for ever: confirming the sales order only advanced items belonging
to an order whose box had been ticked by hand.

| File | Change |
|---|---|
| `models/dw_opening.py` | `action_sync_quotation_line` marks the quotation as a fabrication order, so the fabrication fields appear and the confirmation carries the item. |
| `models/sale_order.py` | `action_confirm` treats any order that carries manufacturing items as a fabrication order, even if the box was cleared. |
| `tests/test_rule_engine.py` | `TestStageProgression` — 7 tests walking draft → quoted → confirmed → production → ready → delivered, deliberately never ticking the box. |

### The stage flow, as verified

| From | Action | To |
|---|---|---|
| Draft | *Generate Components* | Draft (fills the estimate; it is not a stage change) |
| Draft | *Sync Quotation Line* (needs a quotation on the item) | Quoted |
| Quoted | confirm the sales order | Confirmed |
| Confirmed | *Create Manufacturing Order* (creates the BoM on the way) | In Production |
| In Production | *Set Ready* | Ready |
| Ready | *Set Delivered* | Delivered |

An item with no sales order can be set to *Confirmed* directly and produced;
`test_07` covers that path.

---

## 10. Fix — an item can no longer be stranded by an already confirmed order (2026-09-06)

Found on a live server while walking the flow in the browser. `DW/2026/00002`
was linked to `S00001`, but `S00001` had already been confirmed by hand before
the item was ever synced. *Sync Quotation Line* then refused with *"Quotation
lines can only be changed while the quotation is editable"*, and because the
item had never reached *Quoted*, confirming the order could not carry it
either. The item was stuck in Draft with no button that would move it.

Odoo itself allows lines to be added to a confirmed order — only a **locked**
order is closed to changes — so the guard was stricter than the platform.

| File | Change |
|---|---|
| `models/dw_opening.py` | `action_sync_quotation_line` now refuses only a **cancelled** or **locked** order, and each message says how to clear that. On an order that is already sold, the item goes straight to **Confirmed** instead of waiting for a confirmation that has already happened. |
| `tests/test_rule_engine.py` | `test_08` syncs onto an already confirmed order and asserts the item lands on Confirmed; `test_09` and `test_10` assert the locked and cancelled messages. |
| `i18n/ar.po` | 2 new terms; 1111/1111. |
