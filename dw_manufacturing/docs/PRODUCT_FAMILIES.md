# Configuring a Product Family — إعداد عائلة منتجات

**Configuration → Product Families → New**

A family is the single place that decides how a kind of metal product behaves.
Creating one requires **no development**.

---

## 1. Identification

| Field | Meaning |
|---|---|
| Name (English) / Name (Arabic) | Shown to users in each language |
| Code | Unique per company, used in searches and reports |
| Product Kind | Door, fire rated door, window, facade, gate, fence, handrail, staircase, spiral staircase, canopy, light steel structure, shelving, sheet metal work, custom, other. Changing it preselects a sensible dimension set |
| Company | Leave empty to share the family across all companies |

---

## 2. Quantity and weight

**Quantity Method** — how the finished product is sold and counted:
by unit, by linear meter, by square meter, by cubic meter, by kilogram.

**Weight Method** — how the theoretical weight of one finished unit is derived:

| Method | Formula |
|---|---|
| Sum of Component Theoretical Weights | Σ (component qty per unit × product kg per UoM). The default and the most accurate |
| Manually Entered | The user types the weight on the item |
| Weight per m² × Area | `Weight Factor × area_m2` |
| Weight per m × Length | `Weight Factor × total_length_m` |
| Weight per Unit × Count | `Weight Factor` |

---

## 3. Pricing

| Method | Recommended unit price |
|---|---|
| Cost plus Markup | `estimated unit cost × (1 + markup %)` |
| Price per m² | `Rate × area_m2` |
| Price per Linear Meter | `Rate × total_length_m` |
| Price per Kilogram | `Rate × theoretical weight` |
| Price per Unit | `Rate` |

The item still lets the salesperson override the final unit price.

---

## 4. Dimensions — the important part

**Dimensions Shown** decides exactly which inputs appear on the manufacturing
item form. **Mandatory Dimensions** must be a subset and are validated on save.

Available codes:

```
length      width       height      thickness   diameter
perimeter*  area*       volume*     weight*
leaf_count  post_count  section_count  post_spacing
step_count  step_height step_width  total_rise  stair_angle*
weld_length paint_area  galv_area
```

`*` = computed from the entered ones; they cannot be made mandatory.

### Typical sets

| Product | Dimensions |
|---|---|
| Steel door | width, height, thickness, leaf_count, weld_length, paint_area |
| Fence | length, height, post_spacing, post_count, section_count, weld_length, paint_area, galv_area |
| Straight staircase | total_rise, step_count, step_height, step_width, width, stair_angle, weld_length, paint_area |
| Spiral staircase | total_rise, step_count, step_height, diameter, stair_angle, weld_length, paint_area |
| Canopy | length, width, height, post_count, paint_area, galv_area |
| Sheet metal work | length, width, thickness, paint_area |

### How the geometry is derived

* `perimeter_m` and `area_m2` use `length` if entered, otherwise `width`, against
  `height`. With a length and a width but no height (a flat panel or a canopy
  roof), the area becomes `length × width`. With only a diameter, they become
  the circle perimeter and area.
* `post_count` and `section_count` are derived from `length / post_spacing`
  (`spans = ceil(length ÷ spacing)`, `posts = spans + 1`) and remain editable.
* `total_run_m = step_count × step_width`,
  `stair_slope_length_m = √(rise² + run²)`,
  `stair_angle_deg = atan2(rise, run)`.
* `paint_area_m2 = area × Surface Factor` (default 2, both faces) and
  `galv_area_m2` follows it when the finish is galvanizing. Both stay editable.
* `weld_length_m = perimeter + (leaves + posts) × height`, editable.

---

## 5. Defaults

* **Default Finished Product** — preselected on new items.
* **Default Metal Type**, **Default Finish** — preselected.
* **Default Quality Template** — see `QUALITY.md`.
* **Default Waste Percent** — informative, each rule carries its own waste.

---

## 6. Operations

Each line links a fabrication operation type to a work center and defines the
planned duration:

| Time Mode | Planned minutes |
|---|---|
| Fixed minutes | `setup + value` |
| Minutes per produced unit | `setup + value × item count` |
| Minutes per linear meter | `setup + value × total_length_m` |
| Minutes per square meter | `setup + value × paint_area (or area)` |
| Minutes per kilogram | `setup + value × theoretical weight` |
| Minutes per welding meter | `setup + value × weld_length_m` |

These lines become the planned operations on the item, then the operations of
the generated bill of materials, then the work orders of the manufacturing order.

---

## 7. Component rules

Open the **Component Rules** tab and add one rule per material, sub-assembly,
outsourced service or customer supplied item. See `FORMULA_ENGINE.md`.

---

## 8. Worked example — a steel fence in eight minutes

1. **Family**: name "Steel Fence" / "سياج معدني", code `FENCE`, kind *Fence*,
   quantity by linear meter, weight from components, cost plus 30 %.
2. **Dimensions**: length, height, post_spacing, post_count, section_count,
   weld_length, paint_area, galv_area. Mandatory: length, height.
3. **Operations**: Cutting → Welding → Painting.
4. **Rules**:

| Rule | Method | Definition | Waste |
|---|---|---|---|
| Posts | Guided formula | `post_count × height × 1.2` | 5 % |
| Horizontal rails | Guided formula | `length × 2` | 5 % |
| Mesh infill | Variable | `area × 1` | 8 % |
| Paint | Variable | `paint_area × 1`, conversion 0.125 (8 m² per litre) | – |
| Welding consumable | Variable | `weld_length × 0.12` | – |

5. **Quality template**: stage *Final Product*, tests for post spacing, height,
   straightness, weld quality, fixing points, paint thickness, colour.

Create a quotation, add a manufacturing item of the family, enter length 20 000 mm,
height 2 000 mm, post spacing 2 500 mm, press **Generate Components** and the
system produces 9 posts, 8 sections, 22.68 m of post tube, 42 m of rail tube,
43.2 m² of mesh, the paint litres and the electrode kilograms, with the estimated
cost, the recommended price and the three planned operations.
