# Scrap and Reusable Off-cuts — الهالك والبواقي

## 1. Scrap reasons

**Configuration → Process → Scrap Reasons** (`dw.scrap.reason`)

| Field | Purpose |
|---|---|
| Scrap Type | cutting loss, reusable off-cut, manufacturing defect, material defect, design change, handling damage, rework loss, other |
| Planned Scrap | Expected by the estimate; does **not** raise the scrap alert |
| Produces Reusable Off-cut | Shows the *Register Off-cut* button once the scrap is validated |
| Requires Approval | Blocks validation until a supervisor approves |
| Default Responsible | Prefills the responsible user |

Seven reasons are installed by default.

> Odoo 19 also ships `stock.scrap.reason.tag`. The two coexist: the standard tag
> is a free label, `dw.scrap.reason` adds the fabrication behaviour (planned,
> reusable, approval, default owner) that the costing and alert engines need.

## 2. Recording scrap

Scrap is recorded with the **standard** `stock.scrap` document. The module adds:

* Fabrication Scrap Reason, Planned, Reusable
* Operation and Work Center where it happened
* Responsible user
* Manufacturing Item and Project (auto-filled from the manufacturing order)
* Scrap Value — from the real move valuation when the move is done, otherwise
  from the product cost
* Scrap Weight (kg) — from the product's theoretical weight per UoM
* Approval flag, approver and approval note

Validating a scrap linked to a manufacturing order re-runs the actual costing
engine automatically.

### Cost treatment

See `ACTUAL_COSTING.md` §4. In short: scrap taken from stock is an extra cost,
scrap taken from work in progress was already charged as a raw material and is
recorded at zero to avoid double counting — the weight is always recorded.

## 3. Reusable off-cuts

**Operations → Material Off-cuts** (`dw.material.offcut`)

The remnant of a 6 m bar after cutting 4.3 m is not waste, it is stock. The
off-cut record captures:

| Group | Fields |
|---|---|
| Material | product, UoM, quantity, weight, value |
| Dimensions | length, width, thickness, diameter in mm |
| Storage | warehouse, storage location, barcode (auto `OFC/YYYY/#####`) |
| Origin | source scrap, manufacturing order, manufacturing item, project |
| Use | used in which manufacturing order, creation date, last use date |

### Life cycle

```
draft ──Return to Stock──▶ available ──Reserve──▶ reserved
                               │                     │
                               └────Mark as Used─────┴──▶ used
```

**Return to Stock** creates a real `stock.move` from the company's production
location to the chosen internal location and completes it with the standard
`_action_confirm / _action_assign / _action_done` sequence.

> The module **never writes into `stock.quant`.** All stock changes go through
> `stock.move`. `test_12_offcut_uses_standard_stock_moves` asserts the available
> quantity really increased and that the move reached state *done*.

### Barcode

Every off-cut gets a unique barcode equal to its reference. Print it with any
label report or the standard Odoo barcode controller
(`/report/barcode/Code128/<barcode>` or `/report/barcode/QR/<barcode>`) and scan
it back to find the remnant.

## 4. Reporting

| Report | Where |
|---|---|
| Scrap by reason / material / operation / project | Reporting → Scrap Analysis (pivot, graph, list) |
| Available off-cuts | Reporting → Available Off-cuts |
| Scrap weight vs planned weight | Manufacturing order → Fabrication Cost tab |
| Scrap PDF | Manufacturing order → Print → Scrap Report |

## 5. Alerts

When scrap weight exceeds the configured percentage of the planned weight, a
`scrap_overrun` alert is raised. The threshold comes from the alert rule for the
product family, or from **Settings → Scrap Alert (%)**. Planned scrap reasons do
not trigger it.
