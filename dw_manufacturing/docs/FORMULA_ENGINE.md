# The Safe Quantity Engine — محرك المعادلات الآمن

## 1. Why it is safe

The requirement was explicit: no `eval`, no `safe_eval`, no user written script,
no construct that can execute Python.

The engine honours that **structurally**, not by filtering:

* There is **no field anywhere in the module that stores an expression string.**
  You can verify it: `grep -rn "eval" models/` returns nothing but the word
  inside comments, and `dw.component.rule` has no `expression`, `formula_text`
  or `python_code` field.
* A formula is a stored, ordered list of `dw.component.rule.term` records.
  Each term is either a **variable chosen from a closed catalogue** or a
  **numeric constant**, combined with one of five arithmetic operators.
* Evaluating a formula is a `for` loop over those records.
* Variables are read with `getattr` against a **hard-coded mapping** of
  code → field name. A code that is not in the mapping returns `0.0`.

A user who types `__import__('os').system('rm -rf /')` into a rule name gets a
rule whose name is that string. It is never parsed, compiled or executed. There
is an automated test that asserts exactly this
(`test_rule_engine.test_13_engine_never_evaluates_code`).

---

## 2. The variable catalogue

| Code | Label | Source |
|---|---|---|
| `one` | Constant 1 | always 1.0 |
| `item_qty` | Item Count | `quantity` |
| `length` / `width` / `height` | metres | from the mm inputs |
| `thickness` / `thickness_mm` | metres / millimetres | |
| `diameter` / `diameter_mm` | metres / millimetres | |
| `perimeter` | Perimeter (m) | derived |
| `area` | Area (m²) | derived |
| `volume` | Volume (m³) | derived |
| `weight` | Theoretical weight (kg) | from components or the family method |
| `total_length` | Total linear length (m) | `length` or `perimeter` |
| `leaf_count`, `post_count`, `section_count`, `step_count` | counts | |
| `step_height`, `step_width`, `total_rise` | metres | |
| `stair_angle` | degrees | derived |
| `stair_slope_length` | metres | derived |
| `weld_length`, `paint_area`, `galv_area` | m / m² | |
| `post_spacing` | metres | |

Nothing else can be referenced.

---

## 3. The three calculation methods

### Fixed Quantity
`quantity = fixed_qty`. Use for a lock, a handle, a nameplate.

### Single Variable × Factor
`quantity = variable × factor`. Covers most rules.
Example: mesh = `area × 1`.

### Guided Formula
An ordered list of terms, applied **strictly top to bottom**. The operator of
the first term is ignored — it is the seed.

Example, posts of a fence:

| # | Operator | Operand |
|---|---|---|
| 1 | (ignored) | variable `post_count` |
| 2 | Multiply | variable `height` |
| 3 | Multiply | constant `1.2` |

gives `post_count × height × 1.2`.

Because evaluation is left to right, `length + 4 × 2` on this engine means
`(length + 4) × 2`, **not** `length + (4 × 2)`. The **Formula Preview** field
shows the resulting expression so there is no ambiguity, and there is a test
proving the order (`test_04_formula_operators_are_left_to_right`).

Operators: Add, Subtract, Multiply, Divide, Power.
Division by zero yields `0.0` instead of raising.

---

## 4. Post processing, in order

The result then passes through a fixed pipeline:

```
1. + Extra Quantity
2. × Conversion Factor          (formula unit → component unit; must not be 0)
3. × (1 + Waste % / 100)
4. commercial length rounding   (if enabled)
5. rounding multiple / round mode
6. minimum quantity floor
```

### Commercial length rounding
With **Round to Commercial Length** and a length of 6 m, a need of 40 m becomes
7 bars. **Commercial Output** decides whether the rule returns `42` (meters,
keeping the component in metres) or `7` (pieces).

### Rounding
`Round Mode` alone rounds to whole units. Combined with a
`Rounding Multiple` it rounds to a multiple of that value — for example
`0.5` with mode *up* turns 5.2 m² of sheet into 5.5 m².

### Minimum quantity
Applied last, so a rule can guarantee a minimum purchase or issue quantity.

---

## 5. Conditions

A rule produces nothing unless **every** condition on it is true.
Each condition compares a catalogue variable to a number with
`> >= < <= = !=`.

Example: only add diagonal bracing when the fence is taller than 2.5 m —
condition `height > 2.5`.

---

## 6. Component kinds

| Kind | Behaviour |
|---|---|
| Raw Material | Normal BoM line, costed |
| Sub-Assembly | Normal BoM line; if the product has its own BoM Odoo builds a multi-level structure automatically |
| Outsourced Service | Costed as outsourcing on the estimate, **not** put in the bill of materials |
| Customer Supplied | Optionally in the BoM (`Include in Bill of Materials`), always costed at zero |

---

## 7. Two-pass generation

**Generate Components** evaluates every rule, writes the lines, then evaluates
every rule again. The second pass exists because rules based on the `weight`
variable — galvanizing per kilogram, transport per tonne — can only be resolved
once the material lines exist and the item weight is known. Lines that end up
at zero are removed.

---

## 8. Backward compatibility with phase 1

Phase-1 rules had `basis` + `factor` + `fixed_qty` + `waste_percent` +
`rounding_multiple` and no family. After the upgrade they get
`calc_method = variable`, `conversion_factor = 1`, `round_mode = none`, which
reproduces the phase-1 result exactly. They keep matching by
`finished_product_tmpl_id` + `opening_type`. This is covered by
`test_14_legacy_rule_still_matches` and by the upgrade verification recorded in
`TEST_RESULTS.md`.
