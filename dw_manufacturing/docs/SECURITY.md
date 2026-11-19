# Security — الصلاحيات والاعتمادات

## 1. Groups

No group name, privilege name or category name contains the `&` character,
which is known to break some Odoo user-interface widgets.

### Access level (a single choice, hierarchical)

Privilege **Metal Fabrication / التصنيع المعدني**

| XML id | Name | Arabic | Implies |
|---|---|---|---|
| `group_dw_user` | Fabrication User | مستخدم التصنيع | Sales user, Project user, MRP user |
| `group_dw_supervisor` | Fabrication Supervisor | مشرف التصنيع | Fabrication User |
| `group_dw_manager` | Fabrication Manager | مدير التصنيع المعدني | Supervisor + Sales manager + Project manager + MRP manager + every functional role below |

> `group_dw_user` and `group_dw_manager` keep their phase-1 XML ids, so existing
> user assignments survive the upgrade untouched.

### Functional roles (independent check boxes, combinable with any level)

| XML id | Name | Arabic | Implies |
|---|---|---|---|
| `group_dw_stock` | Fabrication Stock Officer | مسؤول المخزون | Inventory user |
| `group_dw_quality` | Fabrication Quality Officer | مسؤول الجودة | — |
| `group_dw_cost_accountant` | Fabrication Cost Accountant | محاسب التكلفة | — |
| `group_dw_project_manager` | Fabrication Project Manager | مدير المشروع | Project manager |
| `group_dw_profitability` | Fabrication Profitability Access | صلاحية الاطلاع على الربحية | — |

**System administrator** — `base.group_system` implies Fabrication Manager.

## 2. What each role may do

| Object | User | Supervisor | Stock | Quality | Cost Accountant | Project Mgr | Manager |
|---|---|---|---|---|---|---|---|
| Manufacturing items | read/write/create | ✓ | ✓ | ✓ | ✓ | ✓ | + delete |
| Component rules | read | write/create | read | read | read | read | full |
| Product families, dimensions, metals, profiles, operations | read | read | read | read | read | read | full |
| Drawings and revisions | read | write/create, **release** | read | read | read | read | full |
| Quality templates, checks, issues | read | read | read | write/create, **validate** | read | read | full |
| Actual cost lines | read | read | read | read | full, **approve / reopen** | read | full |
| Cost revision log | read | read | read | read | read + create | read | read + create, **never delete** |
| Project cost entries | read/write/create | ✓ | ✓ | ✓ | full, **approve** | write/create | full |
| Scrap reasons | read | read | write/create | read | read | read | full |
| Off-cuts | read | read | write/create, **return to stock** | read | read | read | full |
| Labour rates, overhead rules | read | read | read | read | write/create | read | full |
| Alert rules | read | read | read | read | read | read | full |
| Alerts | read + acknowledge | ✓ | ✓ | ✓ | ✓ | ✓ | full |
| Profitability figures | — | — | — | — | — | — | via Profitability Access |

## 3. Protected operations

| Operation | Protection |
|---|---|
| Modifying actual cost | Only Cost Accountant and Manager may write `dw.production.cost.line` |
| Approving a cost line | Button restricted to Cost Accountant |
| Reopening an approved cost | Button restricted to Cost Accountant; writes a revision row |
| Deleting an approved cost line | **Impossible** — raises `UserError` |
| Deleting the cost revision log | **Impossible** — raises `UserError` |
| Approving scrap | Button restricted to Supervisor; some reasons require it before validation |
| Validating a quality check | Button restricted to Quality Officer |
| Deleting a validated quality check | **Impossible** |
| Releasing a drawing revision | Button restricted to Supervisor |
| Deleting a released or superseded revision | **Impossible** |
| Changing overhead and labour rules | Cost Accountant or Manager |
| Viewing profitability | Profitability Access group |
| Adding a manual estimate item | Cost Accountant or Manager; only **approved** items enter the estimate |

## 4. Multi-company

Every company-scoped model carries a **global** record rule
`[('company_id', 'in', company_ids)]`:

`dw.opening` · `dw.component.rule` · `dw.product.family` · `dw.metal.profile` ·
`dw.production.cost.line` · `dw.project.cost.entry` · `dw.quality.check` ·
`dw.quality.template` · `dw.quality.issue` · `dw.drawing` ·
`dw.material.offcut` · `dw.labor.rate` · `dw.overhead.rule` · `dw.alert` ·
`dw.alert.rule` · `dw.scrap.reason` · `dw.operation.type`

Shareable configuration (families, profiles, scrap reasons, operation types)
also accepts `company_id = False` so a group-wide catalogue can be maintained
once.

`test_05_multi_company_isolation` and `test_06_record_rules_exist_for_every_company_model`
verify this.

## 5. Audit trail

* `mail.thread` tracking on manufacturing items, quality checks, quality issues,
  drawings, drawing revisions, off-cuts and project cost entries
* `dw.production.cost.revision` — immutable log of every change to an approved cost
* `Last Cost Run` on each manufacturing order
* Approver and approval date on cost lines, scrap, expenses and drawing revisions
* `dw.alert` — a persistent record of every threshold breach
