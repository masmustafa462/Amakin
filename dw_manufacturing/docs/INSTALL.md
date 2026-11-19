# Installation and Upgrade Guide — دليل التثبيت والترقية

## 1. Prerequisites — المتطلبات

| Item | Requirement |
|---|---|
| Odoo | 19.0 **Community** (tested against branch `19.0`) |
| PostgreSQL | 12 or newer (tested on 16) |
| Python | 3.10+ (tested on 3.11) |
| Odoo modules | `sale_management`, `mrp`, `project`, `stock_account`, `account` — all Community |
| PDF engine | `wkhtmltopdf` 0.12.6 **with patched Qt** (Odoo's official build) for the Arabic PDF reports |
| Optional | `gettext` (`msgfmt`) and `polib` if you want to re-validate the translation file |

> **Enterprise is not required.** No Enterprise module is listed in `depends`,
> referenced in a view, or needed at runtime.

### wkhtmltopdf note

Use the Odoo-patched build. An unpatched build prints the report body correctly
but silently drops the page header and footer with the message
`The switch --header-html, is not support using unpatched qt, and will be ignored`.

Download: https://github.com/odoo/odoo/wiki/Wkhtmltopdf

---

## 2. Fresh installation — تثبيت جديد

```bash
# 1. put the module in the addons path
cp -r dw_manufacturing /path/to/addons/

# 2. install
./odoo-bin -c odoo.conf -d YOURDB -i dw_manufacturing --stop-after-init
```

Or from the interface: **Apps → Update Apps List → search "Metal Fabrication" → Activate**.

After installation you get a new main menu **Metal Fabrication / التصنيع المعدني**
with Operations, Quality, Costing, Reporting and Configuration.

### What is created automatically

* 21 dimension definitions (length, width, height, thickness, diameter, step count, …)
* 4 metal types and 6 grades (carbon steel, galvanized, stainless, aluminium)
* 4 finish types (primer and paint, powder, hot dip galvanizing, raw)
* 8 reference metal profiles with verified theoretical weights
* 17 fabrication operations (cutting … delivery)
* 7 scrap reasons
* 4 sequences (`DW/`, `QC/`, `OFC/`, `PCE/`)
* 8 security groups and the matching record rules
* 1 disabled scheduled action for the alert scanner

No product families are created: the first family is a deliberate configuration
step, described in `PRODUCT_FAMILIES.md`.

---

## 3. Upgrading from phase 1 — الترقية من المرحلة الأولى

Phase 1 was version `19.0.1.0.x` and shipped `dw.opening`, `dw.opening.component`,
`dw.component.rule`, plus `dw_*` fields on `mrp.production` and `sale.order`.

### 3.1 Back up first

```bash
pg_dump -Fc -f before_phase2.dump YOURDB
```

### 3.2 Upgrade

```bash
cp -r dw_manufacturing /path/to/addons/        # overwrite the phase-1 folder
./odoo-bin -c odoo.conf -d YOURDB -u dw_manufacturing --stop-after-init
```

### 3.3 What happens to existing data

| Phase-1 object | After the upgrade |
|---|---|
| `dw.opening` records | Kept. New fields are added with their defaults; `width_mm`, `height_mm`, `quantity`, `material_cost`, `estimated_cost` are untouched |
| `dw.opening.component` lines | Kept, including quantities and costs |
| `dw.component.rule` records | Kept. `calc_method` defaults to `variable`, so the existing `basis` + `factor` + `waste_percent` behave exactly as before; `conversion_factor` defaults to 1 and `round_mode` to "no rounding" |
| Rules with no product family | Still match by `finished_product_tmpl_id` + `opening_type`, exactly as in phase 1 |
| `mrp.production.dw_opening_id` / `dw_project_id` / `dw_sale_order_id` | Kept |
| `sale.order.dw_*` fields | Kept |
| `group_dw_user`, `group_dw_manager` | Kept — user assignments survive. The groups are renamed on screen to "Fabrication User" / "Fabrication Manager" |
| Sequence `dw.opening` | Kept, numbering continues |

### 3.4 Verified upgrade result

The upgrade was executed against a database that contained real phase-1 data
(one quotation, one manufacturing item 1000 × 2100 mm × 2 units, one legacy
component rule based on perimeter with 10 % waste). Result:

```
before : 19.0.1.0.4   DW/2026/00001  1000 x 2100  qty 2  material_cost 170.50
after  : 19.0.2.0.0   DW/2026/00001  1000 x 2100  qty 2  material_cost 170.50
         component qty/unit 6.82   total 13.64   cost 170.50
         legacy rule still matches the legacy item
         regenerating the estimate reproduces exactly the same numbers
```

Zero errors and zero warnings during the upgrade.

### 3.5 Rollback

```bash
dropdb YOURDB && createdb YOURDB
pg_restore -d YOURDB before_phase2.dump
# restore the phase-1 module folder as well
```

---

## 4. Enabling Arabic — تفعيل اللغة العربية

1. **Settings → Translations → Languages**, activate **Arabic (ar_001)**
   (or any `ar_XX` variant — the module ships a base `ar.po` that applies to all).
2. **Settings → Translations → Load a Translation** if the module was installed
   before the language was activated, or run:

```bash
./odoo-bin -c odoo.conf -d YOURDB --load-language=ar_001 --stop-after-init
./odoo-bin -c odoo.conf -d YOURDB -u dw_manufacturing --stop-after-init
```

3. Set the language on each user (**Preferences → Language**) and, for printed
   documents, on the customer record so quotations and reports print in Arabic.

The interface switches to right-to-left automatically. The PDF reports detect
the printing language and flip the whole document to RTL through the shared
`dw_report_wrapper` template.

### Arabic font

The module ships **Amiri** (SIL Open Font License 1.1) under
`static/src/fonts/`, referenced by an `@font-face` rule in
`static/src/scss/dw_report_arabic.scss`. You do **not** need to install an
Arabic font on the server: reports render correctly on a bare system.
The licence text is in `static/src/fonts/AMIRI-LICENSE.txt`.

---

## 5. Post-install configuration checklist

1. **Configuration → Settings** — costing options and alert thresholds.
2. **Configuration → Costing → Labour Rates** — at least one company-wide rate,
   otherwise actual labour cost stays at zero.
3. **Configuration → Costing → Overhead Rules** — optional.
4. **Manufacturing → Work Centers** — set `Cost per hour` for machine cost.
5. **Configuration → Materials → Metal Profiles** — link every raw material
   product to a profile so theoretical weights work.
6. **Configuration → Product Families** — create your first family
   (see `PRODUCT_FAMILIES.md`).
7. **Quality → Inspection Templates** — one template per family and stage.
8. Assign users to the groups described in `SECURITY.md`.

---

## 6. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| "No active component rule matches this product family or finished product." | The item has a family but no rule references that family, or a legacy item has no rule for its finished product template. |
| Actual labour cost is zero | No `dw.labor.rate` matches. Create at least one rate with no user, work center or operation set — it acts as the company fallback. |
| Machine cost is double counted | Your work center `Cost per hour` already includes the operator. Enable **Settings → Metal Fabrication → Work center rate includes labour**. |
| Manufacturing order refuses to close | A mandatory quality check has not passed. Either pass it or disable the gate in Settings. |
| Arabic PDF shows separated letters | The report CSS did not load. Check that the asset bundle `web.report_assets_common` is being served and that `web.base.url` points at a URL the server can reach itself. |
| Header and footer missing in PDF | Unpatched wkhtmltopdf — install the Odoo build. |
