# Changelog

## 19.0.1.0.0 — Odoo 18 → Odoo 19 Community compatibility upgrade

Compatibility-only upgrade. No business logic, field names, menus, workflows,
report layouts or Arabic labels were changed except where Odoo 19 removed the
API being used.

Every item below was verified against the actual `odoo/odoo` `19.0` branch
sources (ORM, RNG view schemas, `account`, `hr`, `uom`, `base`) rather than
assumed.

---

### 1. Manifest

| File | Change |
|---|---|
| `__manifest__.py` | `version` `18.0.2.0.0` → `19.0.1.0.0` |

Dependencies (`base`, `mail`, `hr`, `account`, `product`, `analytic`) were all
confirmed to still exist in Odoo 19 Community and are unchanged.

Removed from the tree: all `__pycache__/` directories and `*.pyc` artifacts
(5 directories, 25 files).

---

### 2. Python — removed/renamed ORM APIs

| File | Change | Why |
|---|---|---|
| `models/custody_category.py`, `models/custody_type.py` | `_sql_constraints = [...]` → `_code_company_uniq = models.Constraint(...)` | **Breaking.** `odoo/orm/model_classes.py:162` logs *"Model attribute '_sql_constraints' is no longer supported"* and ignores it. The unique constraints would have been **silently dropped** from the database. |
| `models/custody_category.py`, `models/custody_type.py` | `name_get()` → `_compute_display_name()` with `@api.depends` | **Breaking.** `name_get` no longer exists anywhere in `odoo/orm/models.py`; it is never called, so display names would silently fall back to `name`. Output string is byte-identical to the old `name_get`. |
| `models/custody_category.py` | `if not self._check_recursion()` → `if self._has_cycle()` | `_check_recursion` is decorated `@api.deprecated` since 18.0. Note the inverted polarity — `_has_cycle()` returns the negation of `_check_recursion()`. |
| `models/employee_custody.py` | `group_operator="avg"` → `aggregator="avg"` | Renamed in 18.0; `odoo/orm/fields.py:485` still accepts it but emits a `DeprecationWarning`. |
| `wizards/custody_statement_report_wizard.py` | Module-level `_()` → `LazyTranslate` (`_lt`) for `SETTLEMENT_KIND_LABEL` and `ISSUE_LABEL` | `_()` resolves at **import** time, when no user language is bound, permanently freezing those five labels untranslated. `_lt` defers the lookup to `str()`. |

### 3. Python — removed `account` fields

| File(s) | Change | Why |
|---|---|---|
| `models/res_company.py`, `models/custody_type.py`, `models/employee_custody.py`, `models/employee_custody_settlement.py`, `wizards/custody_settlement_wizard.py` | Dropped the `('deprecated', '=', False)` leaf from **20** `account.account` domains | **Breaking.** `account.account.deprecated` existed in 18.0 (`account_account.py:52`) and is **removed in 19.0`.` Every one of these 20 domains would have raised an invalid-field error when the field or view loaded. Odoo 19 uses `active` for this, and m2o domains already filter archived records via `active_test`, so behaviour is preserved. |
| `models/employee_custody.py`, `models/employee_custody_line.py`, `models/employee_custody_settlement.py`, `wizards/custody_settlement_wizard.py`, `wizards/custody_return_wizard.py` | `digits="Product Unit of Measure"` → `digits="Product Unit"` (7 fields) | The `decimal.precision` record `uom.decimal_product_uom` was **renamed** in 19.0 (`addons/uom/data/uom_data.xml`). The old name resolves to nothing, so quantity fields would have silently used default precision instead of the configured UoM precision. |

---

### 4. Security

| File | Change | Why |
|---|---|---|
| `security/custody_security.xml` | Added `res.groups.privilege` record `res_groups_privilege_custody`; all 5 groups now use `privilege_id` instead of `category_id`; added explicit `sequence` per tier | **Breaking.** `res.groups.category_id` **no longer exists** in Odoo 19 — it was replaced by `privilege_id` → `res.groups.privilege` (which itself carries the `ir.module.category` link). Loading the old file aborts the install with an invalid-field error. Matches the pattern in `addons/hr/security/hr_security.xml`. |
| `security/custody_security.xml` | Removed `<field name="global" eval="True"/>` from 5 `ir.rule` records | `ir.rule.global` is now `compute='_compute_global', store=True` with **no inverse** (`ir_rule.py:276`), i.e. read-only. It is derived automatically as *"has no groups"* — which all 5 rules already satisfy, so the rules stay global. No core 19 module sets it. |

The five-tier group model, all record rules and every row of
`ir.model.access.csv` are otherwise unchanged. A cross-reference check
confirms all 31 ACL rows resolve, and every non-abstract model has an ACL entry.

---

### 5. Views

| File | Change | Why |
|---|---|---|
| `views/employee_custody_views.xml` | Kanban `<t t-name="kanban-box">` → `<t t-name="card">`; removed the now-redundant `oe_kanban_card oe_kanban_global_click` wrapper `<div>`; bottom row moved into `<footer>` | **Breaking.** `kanban_arch_parser.js:139-141` throws `Missing 'card' template.` — the kanban view would fail to render at all. |
| `views/employee_custody_views.xml`, `views/employee_custody_settlement_views.xml` | Search-view `<group string="تجميع حسب" expand="0">` → `<group>` (2 views) | **Breaking.** The Odoo 19 `common.rng` `group` definition permits only `colspan`, `rowspan`, `fill`, `height`, `width`, `name`, `color`, `invisible` (+ overload/access). `string` and `expand` fail RNG validation at install. Group-by filters themselves are untouched. *(Note: `<group string="…">` in **form** views is still fine — form views have no RNG in 19.0.)* |
| `views/custody_category_views.xml` | Archive stat button using `widget="boolean_button"` → `web_ribbon` + hidden `active` field | `boolean_button` was removed from the Odoo 19 field registry (`addons/web/static/src/views/fields/`) and has zero usages in core 19. Archiving is unaffected and remains available from the Actions menu. |
| `views/employee_custody_views.xml`, `views/custody_type_views.xml` | `bg_color="bg-danger"` → `text-bg-danger`, `bg-success` → `text-bg-success` (3 ribbons) | Bootstrap 5 colour pairing used by core 19 ribbons. |
| `views/res_config_settings_views.xml` | `custody_employee_due_account_id` moved out of the "Loss/Damage" `<setting>` into its own `<setting>` | Pre-existing markup bug — the field was nested inside another setting block and rendered incorrectly. |
| `views/custody_type_views.xml` | Indentation fix on `employee_due_account_id` | Cosmetic. |
| `views/res_config_settings_views.xml` | Settings action: removed `<field name="target">inline</field>`, added `'bin_size': False` to context | **Breaking — caught by a real install traceback.** `ir.actions.act_window.target` dropped the `inline` value in 19 (18.0 had `('inline', 'Inline Edit')`; 19.0 allows only `current` / `new` / `fullscreen` / `main`), raising `ValueError: Wrong value for ir.actions.act_window.target: 'inline'`. Core 19 settings actions omit `target` entirely and pass `bin_size`. |

Verified as **still valid** in 19 and therefore left alone: `<list>`, `<chatter/>`,
`invisible=`/`readonly=`/`required=` expression attributes, `column_invisible`,
`optional`, `sum`, `decoration-*`, `widget="statinfo|badge|handle|monetary|progressbar|analytic_distribution|color_picker|many2many_binary"`,
the `<app>/<block>/<setting>` settings structure, and all three inherited-view
xpath targets (`hr.view_employee_form`, `hr.view_employee_tree`,
`account.view_move_form` — each confirmed to still exist with the targeted nodes).

---

### 6. Reports

| File | Change | Why |
|---|---|---|
| `reports/custody_ledger_template.xml` (6), `custody_handover_template.xml` (1), `custody_clearance_template.xml` (1) | `t-esc` → `t-out` (8 occurrences) | `ir_qweb.py:2490` logs *"Found deprecated directive @t-esc … Replace by @t-out"*. Identical escaping semantics. |

`web.external_layout` and `web.html_container` both confirmed present in 19.0.
Report actions, `binding_model_id`, `print_report_name`, the RTL `dir="rtl"`
layout and all Arabic report content are unchanged.

---

### 7. Accounting

**No logic changes.** The over-settlement engine is untouched and still behaves
as specified — for a 5,000 custody settled against a 6,000 expense:

- one combined balanced move: `Dr Expense 6,000 / Cr Custody 5,000 / Cr Employee Due 1,000`
- the full 6,000 hits the expense account; settlement is **not** capped to the balance
- a child custody is created defaulting to the full 6,000, with the 1,000 difference frozen in `original_remaining_amount`
- on issue, `_auto_settle_employee_due()` posts `Dr Employee Due 1,000 / Cr Custody 1,000` against the **frozen** difference, leaving 5,000 effective balance

All accounting APIs the module calls were verified to still exist in 19.0:
`_reverse_moves(default_values_list, cancel)`, `action_post()`, `reconcile()`,
`account.tax.compute_all()`, `invoice_repartition_line_ids`,
`account.move.line.tax_repartition_line_id` / `tax_base_amount` / `full_reconcile_id`,
`account.account.company_ids` / `reconcile`, and the `liability_payable` account type.

Multi-company handling is unchanged: `company_id` remains on custody, settlement,
line and type; `_check_company_auto` and the `check_company=True` markers are
intact; and the five company record rules still scope on `company_ids`.

---

### 8. Tests

| File | Change |
|---|---|
| `tests/common.py` | Fixture now also creates an `Employee Due` (`liability_payable`) account and sets `company.custody_employee_due_account_id` |

The fixture previously left that account unset, so the over-settlement /
employee-due path could not run under test at all.

---

---

### 9. Verification

Static verification only (no runtime available — see Known gaps). Five checks,
all passing:

1. **Python compilation** of every module file.
2. **XML well-formedness** + **RelaxNG validation** of all 9 list/search/pivot/graph
   arches against Odoo 19's *actual* `search_view.rng` / `list_view.rng` /
   `pivot_view.rng` / `graph_view.rng` / `common.rng`. (Form views have no RNG
   in 19.0 and are checked for well-formedness only.)
3. **Cross-references**: all 31 ACL rows resolve to real models and groups,
   every non-abstract model has an ACL entry, all `groups=`/`ref=`/`parent=`/`action=`
   xmlids resolve, all view fields exist on their model, manifest ↔ disk agree.
4. **Selection values**: every selection-typed value written from XML or Python
   action dicts, checked against the 19.0 selection lists.
5. **Core-model field names and writability**: every `<field>` in every
   `<record>` targeting a core model, resolved through `_inherit`/`_inherits`
   chains against the downloaded 19.0 sources, including a read-only check
   for computed-without-inverse fields.

Checks 4 and 5 were added *after* the `target='inline'` install failure, which
neither of the original checks could have caught — 4 reproduces that exact
error when the bug is reintroduced.

## Known gaps

- **The module has not been installed or run.** See the caveat in the handover
  notes — there was no Odoo 19 runtime, PostgreSQL or Docker available on this
  machine (and system Python is 3.9, below Odoo 19's 3.10 floor). Verification
  was static: Python compilation, XML well-formedness, RNG validation against
  Odoo 19's real schemas, and cross-reference checks — plus per-API confirmation
  against the 19.0 sources.
- **No `i18n/ar.po` was added.** All user-facing strings in this module are
  authored directly in Arabic as the source terms, so an `ar.po` would be an
  identity mapping and add nothing. What would be genuinely useful is an
  `en.po` (Arabic source → English), which needs a translation pass rather than
  a mechanical one.
- **Over-settlement is still not covered by tests.** `test_04_over_settlement_blocked`
  only exercises the raw-record `ValidationError` guard; the combined 3-leg move,
  the child-custody creation and `_auto_settle_employee_due()` have no test.
