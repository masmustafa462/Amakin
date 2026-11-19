# -*- coding: utf-8 -*-
"""The semantic layer — teach the model your business, once.

A language model pointed at a raw Odoo database is doing archaeology. It sees
``account.move`` with 180 fields and has to infer that ``amount_residual`` is
what your finance team calls "outstanding", that a customer invoice is
``move_type = 'out_invoice'``, and that "churned" is a state your company
defined in a custom selection field. It usually gets there. When it does not,
it does not say so — it answers confidently with the wrong number.

Three records fix that, and none of them require code:

* **Glossary** — "ARR means the sum of ``recurring_total`` on active
  subscriptions, excluding trials." Now the term has one meaning, yours.
* **Metric** — a named, reviewed calculation. The AI asks for ``arr`` and gets
  the number your CFO would have produced, not the one it improvised from a
  read_group.
* **Model hint** — "For revenue questions use account.move, not sale.order;
  sale.order includes quotations that never became money." This is the single
  highest-value thing you can write down, because it stops the wrong query
  before it is made.

Everything here narrows and clarifies. Nothing here grants access: a metric
runs as the API key's user, inside that key's model whitelist, and a glossary
entry pointing at a model the key cannot read simply is not shown.
"""
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

AGGREGATES = [
    ("count", "Count of records"),
    ("sum", "Sum"),
    ("avg", "Average"),
    ("min", "Minimum"),
    ("max", "Maximum"),
]

PERIODS = [
    ("none", "No time window"),
    ("today", "Today"),
    ("this_week", "This week"),
    ("this_month", "This month"),
    ("this_quarter", "This quarter"),
    ("this_year", "This year"),
    ("last_7", "Last 7 days"),
    ("last_30", "Last 30 days"),
    ("last_90", "Last 90 days"),
    ("last_365", "Last 365 days"),
]


class McpGlossary(models.Model):
    """A business term the AI should not have to guess at."""

    _name = "mn.mcp.glossary"
    _description = "MCP Business Glossary"
    _order = "term"

    term = fields.Char(required=True, index=True,
        help="The word your people actually use. 'Churn', 'MRR', 'live job'.")
    definition = fields.Text(required=True, translate=True,
        help="Say what it means in one or two sentences, the way you would "
             "explain it to a new analyst on their first day.")
    model_id = fields.Many2one("ir.model", string="Lives on model",
        ondelete="cascade",
        help="Optional. Which model holds this concept.")
    model_name = fields.Char(related="model_id.model", store=True,
                             string="Technical model")
    field_name = fields.Char(
        help="Optional. The field that carries it, if it is one field.")
    example_domain = fields.Text(
        help="Optional. The Odoo domain that expresses it, as an example the "
             "model can copy.")
    synonyms = fields.Char(
        help="Comma-separated. Other things people call this.")
    active = fields.Boolean(default=True)

    _term_uniq = models.Constraint(
        "unique(term)", "That term is already in the glossary.")

    @api.constrains("example_domain")
    def _check_example_domain(self):
        for entry in self:
            if not entry.example_domain:
                continue
            try:
                parsed = eval(entry.example_domain, {"__builtins__": {}}, {})  # noqa: S307
            except Exception as exc:  # noqa: BLE001
                raise ValidationError(_("That example domain does not parse: %s", exc))
            if not isinstance(parsed, list):
                raise ValidationError(_("A domain must be a list."))

    def to_dict(self):
        self.ensure_one()
        out = {"term": self.term, "definition": self.definition}
        if self.model_name:
            out["model"] = self.model_name
        if self.field_name:
            out["field"] = self.field_name
        if self.example_domain:
            out["example_domain"] = self.example_domain
        if self.synonyms:
            out["synonyms"] = [s.strip() for s in self.synonyms.split(",") if s.strip()]
        return out


class McpModelHint(models.Model):
    """What a newcomer needs told about one model before querying it."""

    _name = "mn.mcp.model.hint"
    _description = "MCP Model Hint"
    _order = "model_name"

    model_id = fields.Many2one("ir.model", string="Model", required=True,
                               ondelete="cascade")
    model_name = fields.Char(related="model_id.model", store=True, index=True,
                             string="Technical model")
    summary = fields.Text(required=True, translate=True,
        help="What this model is for, in your business. Two sentences.")
    key_fields = fields.Char(
        help="Comma-separated. The handful of fields that actually matter — "
             "the model reads these first instead of all 180.")
    caveats = fields.Text(translate=True,
        help="What goes wrong here. 'sale.order includes quotations that "
             "never became money — use account.move for revenue.'")
    example_questions = fields.Text(
        help="One per line. Questions this model can answer.")
    active = fields.Boolean(default=True)

    _model_uniq = models.Constraint(
        "unique(model_id)", "There is already a hint for that model.")

    def to_dict(self):
        self.ensure_one()
        out = {"model": self.model_name, "summary": self.summary}
        if self.key_fields:
            out["key_fields"] = [f.strip() for f in self.key_fields.split(",") if f.strip()]
        if self.caveats:
            out["caveats"] = self.caveats
        if self.example_questions:
            out["example_questions"] = [q.strip() for q in
                                        (self.example_questions or "").splitlines() if q.strip()]
        return out

    @api.model
    def for_model(self, model_name):
        return self.sudo().search(
            [("model_name", "=", model_name), ("active", "=", True)], limit=1)


class McpMetric(models.Model):
    """A named number, defined once, that the AI can ask for by name.

    The alternative is the model assembling a read_group on the fly every time
    somebody asks for revenue. That works right up until two people ask the
    same question and get two different answers, and neither is wrong enough
    to notice.
    """

    _name = "mn.mcp.metric"
    _description = "MCP Business Metric"
    _order = "sequence, name"

    name = fields.Char(required=True, index=True,
        help="Lowercase identifier the AI uses: 'mrr', 'open_pipeline'.")
    sequence = fields.Integer(default=10)
    title = fields.Char(translate=True, help="Human label: 'Monthly Recurring Revenue'.")
    description = fields.Text(required=True, translate=True,
        help="The AI reads this to decide when the metric answers the question.")
    active = fields.Boolean(default=True)

    model_id = fields.Many2one("ir.model", string="Model", required=True,
                               ondelete="cascade")
    model_name = fields.Char(related="model_id.model", store=True,
                             string="Technical model")
    domain = fields.Text(default="[]", help="Which records count.")

    aggregate = fields.Selection(AGGREGATES, default="count", required=True)
    measure_field = fields.Char(
        help="The numeric field to aggregate. Not needed for a count.")

    groupby = fields.Char(
        help="Optional. Comma-separated fields to break the number down by. "
             "'stage_id' or 'invoice_date:month'.")

    date_field = fields.Char(
        help="The date field the time window applies to, e.g. invoice_date.")
    default_period = fields.Selection(PERIODS, default="none", required=True)

    unit = fields.Char(help="'SAR', '%', 'days'. Shown with the number so the "
                            "model does not have to guess.")
    call_count = fields.Integer(readonly=True, default=0)

    _name_uniq = models.Constraint("unique(name)", "Metric names must be unique.")

    # ------------------------------------------------------------------
    @api.constrains("name")
    def _check_name(self):
        for metric in self:
            if not NAME_RE.match(metric.name or ""):
                raise ValidationError(_(
                    "'%s' is not a usable metric name. Lowercase letters, "
                    "digits and underscores, starting with a letter.",
                    metric.name))

    @api.constrains("domain")
    def _check_domain(self):
        for metric in self:
            if not metric.domain:
                continue
            try:
                parsed = eval(metric.domain, {"__builtins__": {}}, {})  # noqa: S307
            except Exception as exc:  # noqa: BLE001
                raise ValidationError(_("That domain does not parse: %s", exc))
            if not isinstance(parsed, list):
                raise ValidationError(_("A domain must be a list."))

    @api.constrains("aggregate", "measure_field")
    def _check_measure(self):
        for metric in self:
            if metric.aggregate != "count" and not metric.measure_field:
                raise ValidationError(_(
                    "A %s needs a field to aggregate.", metric.aggregate))

    @api.constrains("default_period", "date_field")
    def _check_period(self):
        for metric in self:
            if metric.default_period != "none" and not metric.date_field:
                raise ValidationError(_(
                    "A time window needs the date field it applies to."))

    # ------------------------------------------------------------------
    def _period_domain(self, period):
        """Translate a named window into a domain on the metric's date field.

        Built from the *user's* today, not the server's: a metric asked for at
        01:00 in Riyadh must not answer with yesterday because the server runs
        in UTC.
        """
        self.ensure_one()
        period = period or self.default_period or "none"
        if period == "none" or not self.date_field:
            return []
        today = fields.Date.context_today(self)
        from datetime import timedelta
        if period == "today":
            start, end = today, today
        elif period == "this_week":
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
        elif period == "this_month":
            start = today.replace(day=1)
            end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        elif period == "this_quarter":
            q_start_month = 3 * ((today.month - 1) // 3) + 1
            start = today.replace(month=q_start_month, day=1)
            end = (start + timedelta(days=100)).replace(day=1) - timedelta(days=1)
        elif period == "this_year":
            start = today.replace(month=1, day=1)
            end = today.replace(month=12, day=31)
        elif period.startswith("last_"):
            days = int(period.split("_")[1])
            start, end = today - timedelta(days=days), today
        else:
            return []
        return [(self.date_field, ">=", fields.Date.to_string(start)),
                (self.date_field, "<=", fields.Date.to_string(end))]

    def to_schema(self):
        """This metric as an MCP tool definition."""
        self.ensure_one()
        return {
            "name": "metric_%s" % self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "enum": [p[0] for p in PERIODS],
                        "description": ("Time window. Defaults to '%s'."
                                        % self.default_period),
                    },
                    "extra_domain": {
                        "type": "array",
                        "description": ("Optional extra Odoo domain, ANDed with "
                                        "the metric's own filter. Use it to narrow, "
                                        "e.g. one customer."),
                    },
                },
                "required": [],
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string"},
                    "value": {"type": "number"},
                    "unit": {"type": "string"},
                    "period": {"type": "string"},
                    "breakdown": {"type": "array"},
                },
                "required": ["metric", "value"],
            },
            "annotations": {"readOnlyHint": True, "destructiveHint": False,
                            "idempotentHint": True, "openWorldHint": False},
        }

    def compute(self, env, arguments):
        """Run the metric as the API key's user. `env` is already scoped."""
        self.ensure_one()
        arguments = arguments or {}
        period = arguments.get("period") or self.default_period
        try:
            base = eval(self.domain or "[]", {"__builtins__": {}}, {})  # noqa: S307
        except Exception:  # noqa: BLE001
            base = []
        extra = arguments.get("extra_domain") or []
        if not isinstance(extra, list):
            extra = []
        domain = list(base) + list(self._period_domain(period)) + list(extra)

        model = env[self.model_name]
        agg = self.aggregate
        spec = "__count" if agg == "count" else "%s:%s" % (self.measure_field, agg)
        groupby = [g.strip() for g in (self.groupby or "").split(",") if g.strip()]

        rows = model._read_group(domain, groupby=groupby, aggregates=[spec])

        breakdown = []
        if groupby:
            total = 0
            for row in rows:
                keys = row[:len(groupby)]
                value = row[len(groupby)]
                total += value or 0
                breakdown.append({
                    "group": [_label(cell) for cell in keys],
                    "value": value,
                })
        else:
            total = rows[0][0] if rows else 0

        self.sudo().call_count += 1
        out = {
            "metric": self.name,
            "title": self.title or self.name,
            "value": total or 0,
            "period": period,
            "record_count": model.search_count(domain),
        }
        if self.unit:
            out["unit"] = self.unit
        if breakdown:
            out["breakdown"] = breakdown
            out["groupby"] = groupby
        return out


def _label(value):
    """A group key a model can actually read."""
    if isinstance(value, models.BaseModel):
        return {"id": value.id, "name": value.display_name} if value else None
    return value
