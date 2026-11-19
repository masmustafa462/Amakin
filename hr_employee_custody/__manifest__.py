{
    "name": "إدارة عهد الموظفين | Employee Custody Management",
    "summary": "نظام متكامل لإدارة العهد المالية والعينية للموظفين مع المحاسبة والتسويات والتقارير",
    "description": """
Employee Custody Management System (إدارة عهد الموظفين)
=========================================================
Enterprise-grade custody lifecycle management:

* Financial and Material custody support
* Full approval workflow (Draft → Submitted → Approved → Issued → Partial → Settled)
* Configurable accounting integration (no hardcoded accounts)
* Multi-company ready, Arabic-first RTL UI
* Settlement wizard (Expense / Return / Salary deduction / Loss)
* Overdue detection with scheduled cron and activity scheduling
* QWeb PDF handover & clearance forms
* Pivot / Graph analytics and custody ledger
* Five-tier security model with record rules
""",
    "author": "Enterprise Odoo Architect",
    "website": "https://www.example.com",
    "category": "Human Resources/Custody",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "hr",
        "account",
        "product",
        "analytic",
    ],
    "data": [
        # Security
        "security/custody_security.xml",
        "security/ir.model.access.csv",

        # Data
        "data/ir_sequence_data.xml",
        "data/custody_category_data.xml",
        "data/custody_type_data.xml",
        "data/mail_template_data.xml",
        "data/ir_cron_data.xml",

        # Wizards
        "wizards/custody_settlement_wizard_views.xml",
        "wizards/custody_settlement_overage_wizard_views.xml",
        "wizards/custody_return_wizard_views.xml",
        "wizards/custody_statement_report_wizard_views.xml",

        # Views
        "views/custody_category_views.xml",
        "views/custody_type_views.xml",
        "views/employee_custody_line_views.xml",
        "views/employee_custody_settlement_views.xml",
        "views/employee_custody_views.xml",
        "views/hr_employee_views.xml",
        "views/res_config_settings_views.xml",
        "views/account_move_views.xml",
        "views/custody_menus.xml",

        # Reports
        "reports/custody_reports.xml",
        "reports/custody_handover_template.xml",
        "reports/custody_clearance_template.xml",
        "reports/custody_ledger_template.xml",
    ],
    "demo": [],
    "installable": True,
    "application": True,
    "auto_install": False,
}
