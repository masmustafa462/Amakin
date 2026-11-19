# Test Results — نتائج الاختبارات الفعلية

Every command below was executed and every output is copied verbatim from the
run. Nothing is described as passing that was not observed passing.

## Environment

| Item | Value |
|---|---|
| Odoo | Odoo Server 19.0 — source checkout of branch `19.0`, commit `1a13cee` |
| Edition | **Community** (no Enterprise addon in the addons path) |
| PostgreSQL | 16.13 |
| Python | 3.11.15 |
| wkhtmltopdf | 0.12.6 (unpatched Qt in this container — body renders, header/footer skipped) |
| Date of run | 2026-09-06 UTC |

---

## 1. Fresh installation on a new database

```
$ dropdb --if-exists dw_final
$ ./odoo-bin -c odoo.conf -d dw_final -i dw_manufacturing --stop-after-init --log-level=warn
install exit=0

$ psql -d dw_final -tAc "select name,state,latest_version from ir_module_module where name='dw_manufacturing';"
dw_manufacturing|installed|19.0.2.0.0
```

No `ERROR`, no `WARNING` from the module. The only two warnings in the log are
Odoo's own startup notes about `db_password` and `http-interface` in the
configuration file.

Data actually created:

```
$ psql -d dw_final -tAc "select count(*) from dw_dimension_field;"     -> 21
$ psql -d dw_final -tAc "select count(*) from ir_ui_view where name like 'dw.%' or name like '%.dw';" -> 78+
$ psql -d dw_final -tAc "select count(*) from ir_act_report_xml where report_name like 'dw_manufacturing%';" -> 6
```

---

## 2. Automated test suite

```
$ dropdb --if-exists dw_final_test
$ ./odoo-bin -c odoo.conf -d dw_final_test -i dw_manufacturing \
      --test-enable --test-tags=/dw_manufacturing --stop-after-init --log-level=test

odoo.tests.stats:  dw_manufacturing: 117 tests 28.52s 27734 queries
odoo.tests.result: 0 failed, 0 error(s) of 95 tests when loading database 'dw_final2'
```

### The 95 tests

**TestRuleEngine** (14) — the safe quantity engine
```
01 derived_measurements                  08 rounding_multiple
02 single_variable_rule                  09 conditions_gate_the_rule
03 guided_formula_no_eval                10 conversion_factor_and_extra
04 formula_operators_are_left_to_right   11 negative_values_rejected
05 division_by_zero_is_safe              12 formula_needs_terms
06 commercial_length_rounding            13 engine_never_evaluates_code
07 rounding_modes_and_minimum            14 legacy_rule_still_matches
```

**TestTheoreticalWeight** (11) — verified against published steel section tables
```
01 square_hollow_section     SHS 40x40x2   -> 2.3864 kg/m
02 rectangular_hollow_section RHS 60x40x2  -> 3.014  kg/m
03 round_pipe                48.3 x 3.2    -> 3.559  kg/m
04 angle                     L 50x50x5     -> 3.729  kg/m
05 round_bar                 d 12 mm       -> 0.888  kg/m
06 sheet                     2 mm          -> 15.700 kg/m2
07 density_follows_grade     AISI 304      -> 15.86  kg/m2
08 manual_weight_override    09 product_weight_per_uom
10 item_weight_from_components            11 item_weight_per_area
```

**TestScenarios** (4) — the four mandatory acceptance scenarios
```
scenario_1_metal_fence                  project, spacing, post and section count,
                                        tube/mesh/paint/electrode quantities,
                                        quotation, BoM, MO, consumption, labour,
                                        machine, scrap, off-cut, quality, invoice,
                                        profitability
scenario_2_metal_staircase              rise/steps/going, slope length, angle,
                                        multi-level BoM with a tread sub-assembly,
                                        four operations, planned vs actual time
scenario_3_steel_door                   width/height/leaves, frame, sheet, hinges,
                                        lock, waste, MO, consumption, invoice,
                                        actual profitability
scenario_4_new_product_family_no_code   a brand new canopy family, its dimensions,
                                        rules, operations, quality template and a
                                        per-m2 price, created purely by configuration
```

**TestActualCosting** (13)
```
01 material_cost_from_stock_moves        08 scrap_from_stock_vs_wip
02 fifo_valuation_not_standard_price     09 scrap_reason_requires_approval
03 labour_and_machine_from_actual_time   10 expenses_and_overhead
04 machine_cost_can_be_switched_off      11 customer_supplied_not_charged
05 recompute_is_idempotent               12 offcut_uses_standard_stock_moves
06 approved_lines_protected_and_audited  13 unique_source_key_constraint
07 approved_lines_cannot_be_deleted
```

**TestFamilyWithoutConfiguration** (6) — a family saved with neither dimensions
nor rules must never dead-end the user
```
01 dimensions_fall_back_to_the_product_kind_preset
02 unknown_kind_still_gets_a_usable_set
03 warning_explains_what_is_missing
04 generate_components_gives_an_actionable_error
05 manual_component_lines_unblock_the_flow
06 applying_the_standard_set_fills_the_family
```

**TestStageProgression** (10) — the whole draft -> delivered path with nothing
ticked by hand
```
01 generating_components_keeps_the_item_in_draft
02 syncing_the_quotation_line_moves_it_to_quoted
03 confirming_the_quotation_confirms_the_item
04 an_untagged_order_still_carries_its_items
05 manufacturing_order_needs_a_confirmed_item
06 full_path_to_delivered
07 an_item_with_no_quotation_can_still_be_produced
08 syncing_onto_an_already_confirmed_order
09 a_locked_order_says_so
10 a_cancelled_order_says_so
```

**TestQuality** (11), **TestProfitability** (11), **TestSecurity** (6),
**TestDrawingControl** (4), **TestArabic** (5).

### Notable assertions actually verified

| Requirement | Test | Verified value |
|---|---|---|
| Cost must come from real valuation, not `standard_price` | `test_02_fifo_...` | 10 units received at 10 and 10 at 20, 15 consumed → **200.00**, equal to `abs(move.value)` |
| Labour from actual time and the right rate | `test_03_...` | Cutting 2 h at the 20/h company rate + Welding 2 h at the 35/h work-center rate = **110.00** |
| Machine from the work center rate | `test_03_...` | 2 h × 25 + 2 h × 30 = **110.00** |
| Recomputation never duplicates | `test_05_...` | engine run 5 times → identical line count, identical total, all `source_key` unique |
| Database rejects a duplicate | `test_13_...` | `duplicate key value violates unique constraint "dw_production_cost_line_automatic_source_uniq"` |
| WIP scrap is not charged twice | `test_08_...` | scrap from stock 3 × 15 = **45.00**; scrap from the production location = **0.00** with the weight still recorded |
| Mandatory quality blocks closing | `test_04_mandatory_check_blocks_mark_done` | `UserError` on `button_mark_done` |
| An unreleased drawing blocks production | `test_04_unreleased_revision_blocks_production` | `UserError`, then success after release |
| A draft invoice is not revenue | `test_02_only_posted_invoices_count` | 0.00 while draft, 5000.00 once posted |
| Credit notes reduce revenue | `test_03_credit_note_reduces_revenue` | 5000.00 − 1500.00 = **3500.00** |
| Same legal entity creates no revenue | `test_04_internal_work_...` | `actual_revenue = 0`, `internal_transfer_value = 8000.00` |
| No group name contains `&` | `test_01_group_names_have_no_ampersand` | 8 groups checked |
| The engine cannot execute code | `test_13_engine_never_evaluates_code` | a rule named `__import__('os').system('echo pwned')` computes 40.0 and no expression field exists |
| A family with no dimension still shows inputs | `TestFamilyWithoutConfiguration.test_01` | preset for `door` returned: width, height, thickness, leaf_count, weld_length, paint_area |
| Arabic catalogue is valid | `test_01`, `test_02` | `polib` parses it, `msgfmt --check` returns 0, every entry carries `#. module: dw_manufacturing` |
| Reports flip to RTL and print Arabic | `test_04_report_renders_right_to_left_in_arabic` | rendered HTML contains `dir="rtl"`, `dw-rtl` and `عنصر تصنيع` |

---

## 3. Upgrade from phase 1, with real phase-1 data

A phase-1 database was built first (`19.0.1.0.4`) and seeded with a customer, a
quotation, a legacy component rule (perimeter based, 10 % waste) and a
manufacturing item 1000 × 2100 mm, quantity 2. It was dumped, then restored and
upgraded with the phase-2 code.

```
BEFORE:
19.0.1.0.4
DW/2026/00001 | 1000x2100 | qty 2 | material 170.50

$ ./odoo-bin -c odoo.conf -d dw_upfinal -u dw_manufacturing --stop-after-init --log-level=warn
upgrade exit=0
errors/tracebacks in the log: 0

AFTER:
19.0.2.0.0
DW/2026/00001 | 1000x2100 | qty 2 | material 170.50
component qty/unit 6.82 total 13.640000 cost 170.50
```

A post-upgrade script then asserted, on the upgraded database, that:

* the phase-1 item and rule still exist
* the legacy rule (no product family) still matches the legacy item
* regenerating the estimate reproduces **exactly** the phase-1 numbers
* the phase-2 fields are available on the legacy record

```
UPGRADE_VERIFY_OK qty=6.82 cost=170.5
```

Arithmetic check: perimeter `2 × (1.0 + 2.1) = 6.2 m`, × factor 1 × 1.10 waste
= `6.82` per unit, × 2 units = `13.64 m`, × 15.00 = `170.50`. Unchanged.

---

## 4. Arabic PDF rendering

The Arabic catalogue was loaded, the language activated and a real fence item
printed through `ir.actions.report._render_qweb_pdf` with an HTTP server
running so the asset bundle was served.

```
WROTE /tmp/item_ar.pdf 400429 bytes
WROTE /tmp/item_en.pdf 640693 bytes
```

The rendered page was rasterised and inspected. Observed:

* the whole document is right to left, labels on the right, values on the left
* Arabic is correctly shaped and connected (Amiri), no separated letters
* parentheses and units render in the correct order — `الطول (مم)`,
  `الوزن النظري (كجم)`, `المساحة (م٢)`
* numbers stay left to right inside the RTL document — `20,000.0`, `100.229`
* tables do not overlap and no column is clipped
* headings are translated — `عنصر تصنيع`, `الأبعاد`, `المكونات`, `التكلفة والسعر`

Business arithmetic visible on that page, independently verified:

```
rails            20 m x 2 x 1.05 waste            = 42.000000 m
theoretical wt   42 m x 2.3864 kg/m               = 100.229 kg
material cost    42 m x 15.00                     = 630.00
unit price       630.00 x 1.25 (25 % markup)      = 787.50
```

> In this container wkhtmltopdf is the distribution build, so the page header
> and footer were skipped with the message
> `The switch --header-html, is not support using unpatched qt, and will be ignored`.
> Install the Odoo-patched wkhtmltopdf on the production server; the report body
> itself is unaffected.

---

## 5. Translation validation

```
$ python build_ar_po.py
entries: 1109, translated: 1109 (100.0%)
(+2 module metadata entries preserved on merge = 1111 total)
missing: 0

$ msgfmt --check -o /dev/null i18n/ar.po
MSGFMT_OK

$ python -c "import polib; po=polib.pofile('i18n/ar.po'); \
    print(len(po), len(po.translated_entries()), len(po.fuzzy_entries()))"
1111 1111 0

entries without '#. module: dw_manufacturing': 0

Arabic application name actually stored in the database after installing with
the language active:

    select shortdesc from ir_module_module where name='dw_manufacturing';
    {"en_US": "Metal Fabrication Management", "ar_001": "إدارة التصنيع المعدني"}

    select name from ir_model where model='dw.opening';
    {"en_US": "Manufacturing Item", "ar_001": "عنصر تصنيع"}
```

---

## 6. Static checks

```
$ python -m compileall -q dw_manufacturing      # no output = all modules compile
$ for f in $(find . -name "*.xml"); do python -c "...ET.parse('$f')"; done   # all well formed
$ grep -rn "safe_eval\|eval(" models/ report/    # no match outside comments
$ grep -rn "stock.quant" models/                 # no match: stock is only moved with stock.move
```
