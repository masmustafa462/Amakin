# Employee Custody Management System (إدارة عهد الموظفين)

Enterprise-grade Odoo 18 module for managing the full lifecycle of employee
custody — both financial (advances, petty cash, travel money) and material
(laptops, vehicles, tools). Arabic-first RTL UI, configurable accounting,
multi-company ready, and fully integrated with HR and Accounting.

---

## 1. Functional Summary

The module treats each custody as a sub-ledger record for a specific
employee. It manages:

* **Request** — the employee (or an officer on their behalf) creates a draft custody.
* **Approval workflow** — optional HR/finance approvals, fully configurable.
* **Issue** — on issue, a posted journal entry debits the custody account and credits cash.
* **Usage tracking** — during the custody period, partial settlements can be recorded.
* **Settlement** — four modes supported: expense, cash return, salary deduction, loss/damage.
* **Reconciliation** — every settlement posts its own move against the custody account until it zeroes out.
* **Material custody** — tracks quantities with partial returns, condition and loss/damage states.

## 2. Technical Architecture

```
hr_employee_custody/
├── __init__.py
├── __manifest__.py
├── README.md
├── data/
│   ├── custody_category_data.xml
│   ├── custody_type_data.xml
│   ├── ir_cron_data.xml
│   ├── ir_sequence_data.xml
│   └── mail_template_data.xml
├── models/
│   ├── __init__.py
│   ├── account_move.py
│   ├── custody_category.py
│   ├── custody_type.py
│   ├── employee_custody.py
│   ├── employee_custody_line.py
│   ├── employee_custody_settlement.py
│   ├── hr_employee.py
│   ├── res_company.py
│   └── res_config_settings.py
├── reports/
│   ├── __init__.py
│   ├── custody_clearance_template.xml
│   ├── custody_handover_template.xml
│   ├── custody_ledger_report.py
│   ├── custody_ledger_template.xml
│   └── custody_reports.xml
├── security/
│   ├── custody_security.xml
│   └── ir.model.access.csv
├── static/description/icon.png
├── tests/
│   ├── __init__.py
│   ├── common.py
│   ├── test_custody_accounting.py
│   ├── test_custody_material.py
│   ├── test_custody_security.py
│   └── test_custody_workflow.py
├── views/
│   ├── account_move_views.xml
│   ├── custody_category_views.xml
│   ├── custody_menus.xml
│   ├── custody_type_views.xml
│   ├── employee_custody_line_views.xml
│   ├── employee_custody_settlement_views.xml
│   ├── employee_custody_views.xml
│   ├── hr_employee_views.xml
│   ├── res_config_settings_views.xml
│   └── account_move_views.xml
└── wizards/
    ├── __init__.py
    ├── custody_return_wizard.py
    ├── custody_return_wizard_views.xml
    ├── custody_settlement_wizard.py
    └── custody_settlement_wizard_views.xml
```

### Domain model

| Model                            | Purpose                                                |
|----------------------------------|--------------------------------------------------------|
| `employee.custody`               | Master record — lifecycle, state machine, accounting. |
| `employee.custody.line`          | Optional breakdown rows (multi-asset custody).        |
| `employee.custody.settlement`    | Settlement transaction (expense/return/salary/loss).  |
| `employee.custody.type`          | Custody type (kind, duration, default accounts).      |
| `employee.custody.category`      | Parent grouping for custody types.                    |
| `hr.employee` (extended)         | Adds `custody_ids`, open count, overdue flag.         |
| `res.company` (extended)         | Feature toggles + default accounts/journal.           |
| `res.config.settings` (extended) | Settings UI for all the above.                        |
| `account.move` (extended)        | Adds `custody_id` back-link, guards against misuse.   |

### State machine

```
draft → submitted → approved → issued → partial → settled
                                   ↓        ↓
                               returned  cancelled
                                   ↓
                            damaged / lost
              (rejected is reachable from draft / submitted / approved)
```

Non-admin users cannot move backwards. Critical fields (amount, product,
quantity, employee, company) are locked after the custody is issued unless
the user is a Custody Admin.

### Accounting engine

Account resolution precedence (per custody):

1. Per-custody override (`custody.journal_id`, `custody.custody_account_id`, …)
2. Custody type (`custody.custody_type_id.journal_id`, …)
3. Company settings (`company.custody_default_journal_id`, …)

Journal entry patterns:

| Event                | Debit                   | Credit               |
|----------------------|-------------------------|----------------------|
| Issue (financial)    | Custody Account         | Cash/Bank Account    |
| Settlement: expense  | Expense Account         | Custody Account      |
| Settlement: return   | Cash/Bank Account       | Custody Account      |
| Settlement: salary   | Payroll Clearing        | Custody Account      |
| Settlement: loss     | Loss Account            | Custody Account      |

Analytic distribution is propagated from the custody or line to the
corresponding move line.

### Security model

Five cumulative groups:

* `group_custody_user` — create/edit own custodies.
* `group_custody_officer` — approve, issue, see all in company.
* `group_custody_accountant` — settle + post journal entries.
* `group_custody_manager` — all companies, full control.
* `group_custody_admin` — reset to draft, unlock locked fields.

Record rules scope visibility by user/company. A self-service rule
restricts regular users to their own custodies.

## 3. Installation Steps

1. Copy the `hr_employee_custody` folder into your Odoo `addons` path.
2. Restart the Odoo service.
3. From the Odoo UI: **Apps → Update Apps List**.
4. Search "إدارة عهد الموظفين" (or `hr_employee_custody`) and click **Install**.
5. Grant the appropriate custody group(s) to the relevant users.
6. Go to **إدارة العهد → الإعدادات → إعدادات الوحدة** and configure:
   * Default journal
   * Custody / Cash / Expense / Salary / Loss accounts
   * Feature toggles

> For a new chart of accounts, make sure the accounts referenced in the
> settings exist. The module does not hardcode any account IDs.

### CLI install

```bash
./odoo-bin -c odoo.conf -d mydb -i hr_employee_custody --stop-after-init
```

### Running the tests

```bash
./odoo-bin -c odoo.conf -d test_db -i hr_employee_custody \
    --test-enable --test-tags=custody --stop-after-init --log-level=test
```

## 4. Test Scenarios

| # | Scenario                                          | Test module                |
|---|---------------------------------------------------|----------------------------|
| 1 | Full financial lifecycle (draft → settled)        | `test_custody_workflow`    |
| 2 | Amount must be > 0                                | `test_custody_workflow`    |
| 3 | Cannot skip state transitions                     | `test_custody_workflow`    |
| 4 | Locked fields after issue                         | `test_custody_workflow`    |
| 5 | Cannot cancel after settle                        | `test_custody_workflow`    |
| 6 | Expected date before issue date rejected          | `test_custody_workflow`    |
| 7 | Issue posts a correct two-line move               | `test_custody_accounting`  |
| 8 | Expense settlement creates partial state          | `test_custody_accounting`  |
| 9 | Full settlement transitions to settled            | `test_custody_accounting`  |
| 10| Over-settlement blocked                           | `test_custody_accounting`  |
| 11| Salary deduction uses the salary clearing account | `test_custody_accounting`  |
| 12| Cancel settlement reverses the move               | `test_custody_accounting`  |
| 13| Material partial return                           | `test_custody_material`    |
| 14| Material full return → state `returned`           | `test_custody_material`    |
| 15| Over-return blocked                               | `test_custody_material`    |
| 16| Mark as lost                                      | `test_custody_material`    |
| 17| Basic user sees only own custodies                | `test_custody_security`    |
| 18| Officer can approve                               | `test_custody_security`    |

## 5. Extending the module

* Additional settlement kinds → extend the `settlement_kind` selection
  and update `_onchange_settlement_kind` + `_prepare_move_vals`.
* Custom reports → add a QWeb template and an `ir.actions.report` bound
  to the `employee.custody` model.
* Integration with Payroll → in your payroll module, read
  `employee.custody.settlement` where `settlement_kind = 'salary'` and
  inject the deduction.

## 6. License

LGPL-3.
