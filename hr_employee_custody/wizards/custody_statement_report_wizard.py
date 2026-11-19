# -*- coding: utf-8 -*-
"""Employee Custody Statement Excel Report.

Wizard parameters:
    * date_from   (required)
    * date_to     (required, must be >= date_from)
    * employee_id (optional -- when blank, all employees are reported)

Output: an xlsx file with one row per movement, grouped by employee, showing:
    Employee | Opening Balance | Movement Date | Movement Type | Debit |
    Credit | Balance

Movement sources:
    * Debits  -- ``employee.custody`` records that have been issued
                 (state in issued/partial/settled). Movement date =
                 ``issue_date``. Movement type = "صرف عهدة".
    * Credits -- ``employee.custody.settlement`` records in ``posted``
                 state. Movement date = ``settlement_date``. Movement
                 type = "تسوية - <kind>" (expense / cash return / salary
                 deduction / loss / damage).

Opening balance is computed from movements strictly before ``date_from``;
movements during the period drive the rolling balance.
"""
import base64
import io
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.translate import LazyTranslate

try:
    import xlsxwriter
except ImportError:  # pragma: no cover
    xlsxwriter = None


# Module-level constants must use the lazy translator: a plain ``_()`` is
# evaluated at import time, when no user language is bound yet, so the term
# would be frozen untranslated. ``_lt`` defers the lookup to ``str()``.
_lt = LazyTranslate(__name__)

SETTLEMENT_KIND_LABEL = {
    "expense": _lt("تسوية - مصروف"),
    "return": _lt("تسوية - إرجاع نقدي"),
    "salary": _lt("تسوية - خصم من الراتب"),
    "loss": _lt("تسوية - فقد / تلف"),
}
ISSUE_LABEL = _lt("صرف عهدة")


class CustodyStatementReportWizard(models.TransientModel):
    _name = "custody.statement.report.wizard"
    _description = "Employee Custody Statement Report Wizard"

    date_from = fields.Date(
        string="من تاريخ",
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
    )
    date_to = fields.Date(
        string="إلى تاريخ",
        required=True,
        default=fields.Date.context_today,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="الموظف",
        help="اتركه فارغاً لعرض جميع الموظفين.",
    )
    company_id = fields.Many2one(
        "res.company",
        string="الشركة",
        default=lambda self: self.env.company,
        required=True,
    )
    file_data = fields.Binary(string="ملف Excel", readonly=True)
    file_name = fields.Char(string="اسم الملف", readonly=True)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise ValidationError(_(
                    "تاريخ (من) يجب أن يكون أصغر من أو يساوي تاريخ (إلى)."
                ))

    # ------------------------------------------------------------------
    # Data gathering
    # ------------------------------------------------------------------
    def _collect_movements(self):
        """Return ({emp_id: [movement_dict, ...]}, {emp_id: opening}, employees).

        Each movement_dict has keys:
            employee_id, employee_name, date, type_label, debit, credit
        """
        self.ensure_one()
        emp_domain = []
        if self.employee_id:
            emp_domain = [("employee_id", "=", self.employee_id.id)]

        # All custodies that reached "issued" -- they create a debit
        # movement at issue_date. We deliberately do NOT include cancelled.
        issued_custody_domain = emp_domain + [
            ("state", "in", ("issued", "partial", "settled")),
            ("issue_date", "!=", False),
            ("issue_date", "<=", self.date_to),
            ("company_id", "=", self.company_id.id),
        ]
        custodies = self.env["employee.custody"].search(
            issued_custody_domain,
            order="issue_date, id",
        )

        # All posted settlements -- they create a credit movement at
        # settlement_date.
        settle_domain = [
            ("state", "=", "posted"),
            ("settlement_date", "<=", self.date_to),
            ("custody_id.company_id", "=", self.company_id.id),
        ]
        if self.employee_id:
            settle_domain.append(
                ("custody_id.employee_id", "=", self.employee_id.id)
            )
        settlements = self.env["employee.custody.settlement"].search(
            settle_domain,
            order="settlement_date, id",
        )

        movements_by_emp = defaultdict(list)
        opening_by_emp = defaultdict(float)
        employees_seen = {}

        for cu in custodies:
            emp = cu.employee_id
            if not emp:
                continue
            employees_seen[emp.id] = emp
            amt = cu.amount or 0.0
            if cu.issue_date < self.date_from:
                opening_by_emp[emp.id] += amt
            else:
                movements_by_emp[emp.id].append({
                    "date": cu.issue_date,
                    "type_label": _("%(label)s (%(name)s)") % {
                        "label": ISSUE_LABEL,
                        "name": cu.name,
                    },
                    "debit": amt,
                    "credit": 0.0,
                    "ref_id": cu.id,
                    "ref_model": "employee.custody",
                })

        for st in settlements:
            emp = st.custody_id.employee_id
            if not emp:
                continue
            employees_seen[emp.id] = emp
            amt = st.amount or 0.0
            label = SETTLEMENT_KIND_LABEL.get(st.settlement_kind) or st.settlement_kind
            if st.settlement_date < self.date_from:
                opening_by_emp[emp.id] -= amt
            else:
                movements_by_emp[emp.id].append({
                    "date": st.settlement_date,
                    "type_label": _("%(label)s (%(name)s)") % {
                        "label": label,
                        "name": st.name or st.custody_id.name,
                    },
                    "debit": 0.0,
                    "credit": amt,
                    "ref_id": st.id,
                    "ref_model": "employee.custody.settlement",
                })

        # Stable sort: by date, then by debit-first (issue) so issue lines
        # appear before same-day settlements.
        for emp_id, lst in movements_by_emp.items():
            lst.sort(key=lambda m: (m["date"], 0 if m["debit"] else 1))

        # Make sure every selected employee shows up even if no movements.
        if self.employee_id and self.employee_id.id not in employees_seen:
            employees_seen[self.employee_id.id] = self.employee_id

        return movements_by_emp, opening_by_emp, employees_seen

    # ------------------------------------------------------------------
    # Excel generation
    # ------------------------------------------------------------------
    def action_generate_xlsx(self):
        self.ensure_one()
        if xlsxwriter is None:
            raise UserError(_(
                "حزمة xlsxwriter غير مثبتة على الخادم. "
                "يرجى تثبيتها لتفعيل تقرير Excel."
            ))

        movements_by_emp, opening_by_emp, employees = self._collect_movements()

        buf = io.BytesIO()
        wb = xlsxwriter.Workbook(buf, {"in_memory": True})

        # Formats -------------------------------------------------------
        f_title = wb.add_format({
            "bold": True, "font_size": 14, "align": "center",
            "valign": "vcenter", "bg_color": "#1F4E78",
            "font_color": "#FFFFFF", "border": 1,
        })
        f_subtitle = wb.add_format({
            "italic": True, "font_size": 10, "align": "center",
            "valign": "vcenter", "bg_color": "#D9E1F2", "border": 1,
        })
        f_emp_header = wb.add_format({
            "bold": True, "font_size": 12, "bg_color": "#FFE699",
            "border": 1, "align": "right",
        })
        f_col_header = wb.add_format({
            "bold": True, "bg_color": "#305496", "font_color": "#FFFFFF",
            "border": 1, "align": "center", "valign": "vcenter",
            "text_wrap": True,
        })
        f_text = wb.add_format({"border": 1, "align": "right"})
        f_text_center = wb.add_format({"border": 1, "align": "center"})
        f_date = wb.add_format({"border": 1, "num_format": "yyyy-mm-dd",
                                 "align": "center"})
        currency_fmt = (
            self.company_id.currency_id.symbol or
            self.env.company.currency_id.symbol or ""
        )
        money_format = "#,##0.00 \"" + (currency_fmt or "") + "\""
        f_money = wb.add_format({"border": 1, "num_format": money_format,
                                  "align": "left"})
        f_money_bold = wb.add_format({
            "border": 1, "num_format": money_format, "bold": True,
            "align": "left", "bg_color": "#E2EFDA",
        })
        f_opening = wb.add_format({
            "border": 1, "num_format": money_format, "bold": True,
            "italic": True, "bg_color": "#FFF2CC", "align": "left",
        })
        f_total_label = wb.add_format({
            "border": 1, "bold": True, "align": "center",
            "bg_color": "#E2EFDA",
        })

        ws = wb.add_worksheet("Custody Statement")
        ws.right_to_left()
        ws.set_column(0, 0, 28)   # Employee
        ws.set_column(1, 1, 18)   # Opening Balance
        ws.set_column(2, 2, 14)   # Movement Date
        ws.set_column(3, 3, 32)   # Movement Type
        ws.set_column(4, 4, 16)   # Debit
        ws.set_column(5, 5, 16)   # Credit
        ws.set_column(6, 6, 18)   # Balance

        # Title block ---------------------------------------------------
        ws.merge_range(0, 0, 0, 6,
                       _("كشف حركة عهد الموظفين"), f_title)
        period_text = _("الفترة: من %(f)s إلى %(t)s") % {
            "f": self.date_from, "t": self.date_to,
        }
        scope_text = (
            _("الموظف: %s") % self.employee_id.name
            if self.employee_id else _("جميع الموظفين")
        )
        ws.merge_range(1, 0, 1, 6, period_text, f_subtitle)
        ws.merge_range(2, 0, 2, 6, scope_text, f_subtitle)
        ws.set_row(0, 26)
        ws.set_row(1, 18)
        ws.set_row(2, 18)

        # Column headers ------------------------------------------------
        headers = [
            _("الموظف"),
            _("الرصيد الافتتاحي"),
            _("تاريخ الحركة"),
            _("نوع الحركة"),
            _("مدين"),
            _("دائن"),
            _("الرصيد"),
        ]
        for c, h in enumerate(headers):
            ws.write(4, c, h, f_col_header)
        ws.set_row(4, 30)

        # Body ----------------------------------------------------------
        row = 5
        grand_debit = 0.0
        grand_credit = 0.0
        grand_closing = 0.0

        ordered_emps = sorted(
            employees.values(), key=lambda e: (e.name or "").lower()
        )
        if not ordered_emps:
            ws.merge_range(row, 0, row, 6,
                           _("لا توجد بيانات في الفترة المحددة."),
                           f_text_center)
            row += 1
        for emp in ordered_emps:
            opening = opening_by_emp.get(emp.id, 0.0)
            mvts = movements_by_emp.get(emp.id, [])

            # Per-employee header row
            ws.merge_range(row, 0, row, 6,
                           _("%s") % emp.name, f_emp_header)
            row += 1

            # Opening balance row
            ws.write(row, 0, emp.name, f_text)
            ws.write(row, 1, opening, f_opening)
            ws.write(row, 2, "", f_text_center)
            ws.write(row, 3, _("الرصيد الافتتاحي"), f_text)
            ws.write(row, 4, 0.0, f_money)
            ws.write(row, 5, 0.0, f_money)
            ws.write(row, 6, opening, f_money_bold)
            row += 1

            running = opening
            emp_debit = 0.0
            emp_credit = 0.0
            for m in mvts:
                running += m["debit"] - m["credit"]
                emp_debit += m["debit"]
                emp_credit += m["credit"]
                ws.write(row, 0, emp.name, f_text)
                ws.write(row, 1, "", f_text_center)
                ws.write_datetime(row, 2, m["date"], f_date)
                ws.write(row, 3, m["type_label"], f_text)
                ws.write(row, 4, m["debit"], f_money)
                ws.write(row, 5, m["credit"], f_money)
                ws.write(row, 6, running, f_money)
                row += 1

            # Per-employee totals
            ws.merge_range(row, 0, row, 3,
                           _("الإجمالي للموظف"), f_total_label)
            ws.write(row, 4, emp_debit, f_money_bold)
            ws.write(row, 5, emp_credit, f_money_bold)
            ws.write(row, 6, running, f_money_bold)
            row += 1
            row += 1  # spacer

            grand_debit += emp_debit
            grand_credit += emp_credit
            grand_closing += running

        # Grand totals --------------------------------------------------
        if ordered_emps:
            ws.merge_range(row, 0, row, 3,
                           _("الإجمالي العام"), f_total_label)
            ws.write(row, 4, grand_debit, f_money_bold)
            ws.write(row, 5, grand_credit, f_money_bold)
            ws.write(row, 6, grand_closing, f_money_bold)

        wb.close()
        data = base64.b64encode(buf.getvalue())
        buf.close()

        fname = _("custody_statement_%s_to_%s.xlsx") % (
            self.date_from, self.date_to,
        )
        self.write({"file_data": data, "file_name": fname})

        return {
            "type": "ir.actions.act_url",
            "url": (
                "/web/content/?model=custody.statement.report.wizard"
                "&id=%s&field=file_data&filename_field=file_name"
                "&download=true"
            ) % self.id,
            "target": "self",
        }
