{
    "name": "Metal Fabrication Management",
    "summary": "Estimate, manufacture, control and cost any fabricated metal product",
    "description": """
Metal Fabrication Management
============================
Doors, fire doors, windows, facades, gates, fences, handrails, straight and
spiral staircases, canopies, light steel structures, shelving, sheet metal work
and any custom metal product configured from the user interface.

Covers configurable product families, a safe formula engine, theoretical weight
calculation, multi level bills of materials, fabrication operations, estimated
and actual costing, scrap and reusable off-cuts, a lightweight quality system,
drawing revision control, project profitability and Arabic reporting.

Runs on Odoo 19 Community only - no Enterprise application is required.
""",
    "version": "19.0.2.0.0",
    "category": "Manufacturing/Manufacturing",
    "author": "Custom",
    "license": "LGPL-3",
    "depends": [
        "sale_management",
        "mrp",
        "project",
        "stock_account",
        "account",
    ],
    "data": [
        "security/dw_security.xml",
        "security/ir.model.access.csv",
        "security/dw_record_rules.xml",
        "data/dw_sequence.xml",
        "data/dw_dimension_data.xml",
        "data/dw_metal_data.xml",
        "data/dw_operation_data.xml",
        "data/dw_cron.xml",
        "views/dw_config_views.xml",
        "views/dw_metal_profile_views.xml",
        "views/dw_quality_views.xml",
        "views/dw_product_family_views.xml",
        "views/dw_component_rule_views.xml",
        "views/dw_drawing_views.xml",
        "views/dw_scrap_views.xml",
        "views/dw_labor_rate_views.xml",
        "views/dw_production_cost_views.xml",
        "views/dw_alert_views.xml",
        "views/dw_opening_views.xml",
        "views/product_views.xml",
        "views/sale_order_views.xml",
        "views/mrp_production_views.xml",
        "views/mrp_bom_views.xml",
        "views/project_views.xml",
        "views/res_config_settings_views.xml",
        "report/dw_report_paperformat.xml",
        "report/dw_report_layout.xml",
        "report/dw_item_report.xml",
        "report/dw_production_cost_report.xml",
        "report/dw_project_profitability_report.xml",
        "report/dw_quality_report.xml",
        "report/dw_report_actions.xml",
        "report/dw_analysis_views.xml",
        "views/dw_menus.xml",
    ],
    "assets": {
        "web.report_assets_common": [
            "dw_manufacturing/static/src/scss/dw_report_arabic.scss",
        ],
    },
    "application": True,
    "installable": True,
}
