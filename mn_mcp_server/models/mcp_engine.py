# -*- coding: utf-8 -*-
"""The MCP engine — every method the protocol exposes, in one place.

This used to live inside the HTTP controller. It was moved out for one
reason: the playground, and anything else that wants to exercise a tool,
must run **the same code the wire runs**. A second implementation for the
test button is a second implementation to get wrong, and it would be wrong in
the most dangerous possible way — the button would say "safe" about a path
nobody had actually taken.

So the controller is now transport. It authenticates, negotiates a revision,
frames a response, and delegates here. Nothing in this file knows about HTTP.
"""
import base64
import json
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# How many entries a list method returns before it hands back a cursor.
PAGE_SIZE = 100


class McpForbidden(Exception):
    """Refused by MCP scope, permission or policy — not an internal error."""


# Tools that never change data, and tools that destroy it. Clients use these
# hints to decide what may run unattended: Claude will call a readOnlyHint
# tool freely and stops to ask before a destructive one.
READ_ONLY_TOOLS = {
    "odoo_search", "odoo_search_count", "odoo_read", "odoo_search_read",
    "odoo_read_group", "odoo_name_search", "odoo_fields_get",
    "odoo_list_models", "odoo_get_view", "odoo_menu_tree",
    "odoo_user_context", "odoo_print_report", "odoo_glossary",
    "odoo_describe_model", "odoo_list_metrics",
}
DESTRUCTIVE_TOOLS = {"odoo_unlink"}


def _schema(required, properties):
    return {"type": "object", "required": list(required), "properties": properties}


# Output schemas. The spec is explicit: a tool that declares outputSchema MUST
# return structuredContent that validates against it. That is worth the extra
# lines — a model handed {"ids": [...], "count": n} with a declared shape stops
# re-parsing prose out of a text block and starts chaining calls reliably.
_OUT_IDS = {"type": "object", "properties": {
    "ids": {"type": "array", "items": {"type": "integer"}},
    "count": {"type": "integer"}}, "required": ["ids", "count"]}
_OUT_COUNT = {"type": "object", "properties": {"count": {"type": "integer"}},
              "required": ["count"]}
_OUT_RECORDS = {"type": "object", "properties": {
    "records": {"type": "array", "items": {"type": "object"}},
    "count": {"type": "integer"}}, "required": ["records"]}
_OUT_ID = {"type": "object", "properties": {"id": {"type": "integer"}},
           "required": ["id"]}
_OUT_IDS_ONLY = {"type": "object", "properties": {
    "ids": {"type": "array", "items": {"type": "integer"}}}, "required": ["ids"]}
_OUT_OK = {"type": "object", "properties": {"ok": {"type": "boolean"}},
           "required": ["ok"]}


class McpEngine(models.AbstractModel):
    _name = "mn.mcp.engine"
    _description = "MCP dispatch engine"

    # ─────────────────────────────────────────────────────────────────
    # limits
    # ─────────────────────────────────────────────────────────────────
    @api.model
    def max_records(self):
        return int(self.env["ir.config_parameter"].sudo().get_param(
            "mn_mcp.max_records", "100"))

    # ─────────────────────────────────────────────────────────────────
    # tools/list
    # ─────────────────────────────────────────────────────────────────
    @api.model
    def _builtin_tools(self):
        tools = [
            # — Core CRUD —
            {"name": "odoo_search",
             "description": "Search records. Returns ids.",
             "inputSchema": _schema(("model",), {
                 "model": {"type": "string"},
                 "domain": {"type": "array"},
                 "limit": {"type": "integer"},
                 "order": {"type": "string"}}),
             "outputSchema": _OUT_IDS},
            {"name": "odoo_search_count",
             "description": "Count records matching a domain.",
             "inputSchema": _schema(("model",), {
                 "model": {"type": "string"}, "domain": {"type": "array"}}),
             "outputSchema": _OUT_COUNT},
            {"name": "odoo_read",
             "description": "Read fields for given ids.",
             "inputSchema": _schema(("model", "ids"), {
                 "model": {"type": "string"},
                 "ids": {"type": "array"}, "fields": {"type": "array"}}),
             "outputSchema": _OUT_RECORDS},
            {"name": "odoo_search_read",
             "description": "Search + read in one call.",
             "inputSchema": _schema(("model",), {
                 "model": {"type": "string"}, "domain": {"type": "array"},
                 "fields": {"type": "array"}, "limit": {"type": "integer"},
                 "order": {"type": "string"}}),
             "outputSchema": _OUT_RECORDS},
            {"name": "odoo_read_group",
             "description": "Group-by aggregation. SQL-style.",
             "inputSchema": _schema(("model", "groupby"), {
                 "model": {"type": "string"}, "domain": {"type": "array"},
                 "fields": {"type": "array"}, "groupby": {"type": "array"}})},
            {"name": "odoo_name_search",
             "description": "Quick name lookup — Odoo's autocomplete primitive.",
             "inputSchema": _schema(("model",), {
                 "model": {"type": "string"}, "name": {"type": "string"},
                 "limit": {"type": "integer"}})},
            {"name": "odoo_create",
             "description": "Create a record. Requires perm_create.",
             "inputSchema": _schema(("model", "values"), {
                 "model": {"type": "string"}, "values": {"type": "object"}}),
             "outputSchema": _OUT_ID},
            {"name": "odoo_create_many",
             "description": "Bulk create multiple records.",
             "inputSchema": _schema(("model", "records"), {
                 "model": {"type": "string"}, "records": {"type": "array"}}),
             "outputSchema": _OUT_IDS_ONLY},
            {"name": "odoo_write",
             "description": "Update records. Requires perm_write.",
             "inputSchema": _schema(("model", "ids", "values"), {
                 "model": {"type": "string"}, "ids": {"type": "array"},
                 "values": {"type": "object"}}),
             "outputSchema": _OUT_OK},
            {"name": "odoo_unlink",
             "description": "Delete records. Requires perm_unlink.",
             "inputSchema": _schema(("model", "ids"), {
                 "model": {"type": "string"}, "ids": {"type": "array"}}),
             "outputSchema": _OUT_OK},
            {"name": "odoo_copy",
             "description": "Duplicate a record.",
             "inputSchema": _schema(("model", "id"), {
                 "model": {"type": "string"}, "id": {"type": "integer"},
                 "default": {"type": "object"}}),
             "outputSchema": _OUT_ID},
            {"name": "odoo_find_or_create",
             "description": "Find record by domain; if not found, create.",
             "inputSchema": _schema(("model", "domain", "values"), {
                 "model": {"type": "string"}, "domain": {"type": "array"},
                 "values": {"type": "object"}}),
             "outputSchema": {"type": "object", "properties": {
                 "id": {"type": "integer"}, "created": {"type": "boolean"}},
                 "required": ["id", "created"]}},
            # — Discovery —
            {"name": "odoo_fields_get",
             "description": "Field schema of a model, plus any hint an "
                            "administrator has written about it.",
             "inputSchema": _schema(("model",), {"model": {"type": "string"}})},
            {"name": "odoo_list_models",
             "description": "Models this key may access, with one-line "
                            "summaries where they have been described.",
             "inputSchema": _schema((), {})},
            {"name": "odoo_get_view",
             "description": "Get a UI view definition (form/list/kanban).",
             "inputSchema": _schema(("model",), {
                 "model": {"type": "string"},
                 "view_type": {"type": "string"}})},
            # — Semantic layer —
            {"name": "odoo_describe_model",
             "description": "How this business uses a model: what it is for, "
                            "which fields matter, and what to watch out for. "
                            "Read this BEFORE building a query on a model you "
                            "have not used in this conversation.",
             "inputSchema": _schema(("model",), {"model": {"type": "string"}}),
             "outputSchema": {"type": "object", "properties": {
                 "model": {"type": "string"}, "summary": {"type": "string"},
                 "key_fields": {"type": "array"}, "caveats": {"type": "string"},
                 "example_questions": {"type": "array"}}}},
            {"name": "odoo_glossary",
             "description": "This company's definitions for its own business "
                            "terms. Look a term up here instead of assuming "
                            "what it means.",
             "inputSchema": _schema((), {
                 "term": {"type": "string",
                          "description": "Optional. Omit to list everything."}}),
             "outputSchema": {"type": "object", "properties": {
                 "terms": {"type": "array"}}, "required": ["terms"]}},
            {"name": "odoo_list_metrics",
             "description": "Named, pre-approved business metrics. Prefer one "
                            "of these over assembling your own aggregation — "
                            "these are the numbers the business agrees on.",
             "inputSchema": _schema((), {}),
             "outputSchema": {"type": "object", "properties": {
                 "metrics": {"type": "array"}}, "required": ["metrics"]}},
            # — Chatter / activities / mail —
            {"name": "odoo_message_post",
             "description": "Post a message on a record's chatter.",
             "inputSchema": _schema(("model", "id", "body"), {
                 "model": {"type": "string"}, "id": {"type": "integer"},
                 "body": {"type": "string"}, "subject": {"type": "string"}})},
            {"name": "odoo_activity_schedule",
             "description": "Schedule a follow-up activity on a record.",
             "inputSchema": _schema(("model", "id", "summary"), {
                 "model": {"type": "string"}, "id": {"type": "integer"},
                 "summary": {"type": "string"}, "date_deadline": {"type": "string"},
                 "user_id": {"type": "integer"}})},
            {"name": "odoo_send_email",
             "description": "Send an email via a mail.template id.",
             "inputSchema": _schema(("template_id", "model", "id"), {
                 "template_id": {"type": "integer"},
                 "model": {"type": "string"},
                 "id": {"type": "integer"},
                 "email_to": {"type": "string"}})},
            # — Reports & attachments —
            {"name": "odoo_print_report",
             "description": "Render a QWeb PDF report. Returns base64.",
             "inputSchema": _schema(("report_name", "ids"), {
                 "report_name": {"type": "string"},
                 "ids": {"type": "array"}})},
            {"name": "odoo_attach_file",
             "description": "Attach a base64 file to a record.",
             "inputSchema": _schema(("model", "id", "name", "datas"), {
                 "model": {"type": "string"}, "id": {"type": "integer"},
                 "name": {"type": "string"}, "datas": {"type": "string"},
                 "mimetype": {"type": "string"}})},
            # — Server actions / generic execute —
            {"name": "odoo_run_server_action",
             "description": "Execute an ir.actions.server by id.",
             "inputSchema": _schema(("action_id",), {
                 "action_id": {"type": "integer"},
                 "model": {"type": "string"},
                 "ids": {"type": "array"}})},
            {"name": "odoo_execute",
             "description": "Call a model method. Whitelist-gated.",
             "inputSchema": _schema(("model", "method"), {
                 "model": {"type": "string"}, "method": {"type": "string"},
                 "args": {"type": "array"}, "kwargs": {"type": "object"}})},
            # — Discovery / helpers —
            {"name": "odoo_menu_tree",
             "description": "Return the app menu tree for the current user.",
             "inputSchema": _schema((), {})},
            {"name": "odoo_user_context",
             "description": "Return current user info + company + lang + tz.",
             "inputSchema": _schema((), {})},
        ]

        from ..controllers import confirm as C

        # Tools behind the confirmation guard advertise the argument that
        # satisfies it, so a model on a client without elicitation can see how
        # to proceed instead of retrying blindly.
        for tool in tools:
            if tool["name"] in C.ALWAYS_CONFIRM or tool["name"] in C.BULK_TOOLS \
                    or tool["name"] in C.METHOD_TOOLS:
                tool["inputSchema"]["properties"]["confirm"] = {
                    "type": "boolean",
                    "description": ("Set true only after the user has agreed to "
                                    "this exact action. The server refuses "
                                    "without it."),
                }

        for tool in tools:
            read_only = tool["name"] in READ_ONLY_TOOLS
            tool["annotations"] = {
                "readOnlyHint": read_only,
                "destructiveHint": tool["name"] in DESTRUCTIVE_TOOLS,
                # Re-running a search is free; re-running a create is not.
                "idempotentHint": read_only,
                "openWorldHint": False,
            }
        return tools

    @api.model
    def tools_list(self, params=None):
        tools = self._builtin_tools()

        # Custom tools and metrics sit alongside the built-ins. They are added
        # here rather than merged later so they get the same sorting and the
        # same cache guarantees.
        tools.extend(t.to_schema()
                     for t in self.env["mn.mcp.tool"].sudo().search([]))
        tools.extend(m.to_schema()
                     for m in self.env["mn.mcp.metric"].sudo().search([]))

        # Deterministic order: 2026-07-28 asks for it so clients can cache the
        # list, and a stable order also keeps the LLM's prompt cache warm — a
        # reshuffled tool list invalidates it on every conversation turn.
        tools.sort(key=lambda t: t["name"])
        return _paginate({"tools": tools}, "tools", params)

    # ─────────────────────────────────────────────────────────────────
    # tools/call
    # ─────────────────────────────────────────────────────────────────
    @api.model
    def tools_call(self, key, env, params):
        """Dispatch one tool call. `env` is already scoped to the key's user."""
        from ..controllers import confirm as C

        name = params.get("name")
        arguments = params.get("arguments") or {}

        # Guard rail: destructive and bulk operations stop here until a human
        # has seen what is about to happen. `confirm` is stripped either way so
        # it can never reach the ORM as a field value.
        confirmed = C.already_confirmed(self.env, params, key, name, arguments)
        arguments = {k: v for k, v in arguments.items() if k != "confirm"}
        if C.needs_confirmation(self.env, name, arguments) and not confirmed:
            self.env["mn.mcp.audit"].sudo().log(
                api_key_id=key.id, method="tools/call", status="ok",
                error_msg="confirmation requested for %s" % name,
                args=params, tool_name=name, model_target=arguments.get("model"),
            )
            return C.input_required(
                name, arguments, key, env,
                offer_elicitation=C.client_supports_elicitation(params))

        # A metric is looked up first: its name is namespaced (metric_*) so it
        # can collide with nothing, and it is the cheapest dispatch.
        if (name or "").startswith("metric_"):
            metric = self.env["mn.mcp.metric"].sudo().search(
                [("name", "=", name[len("metric_"):])], limit=1)
            if metric:
                if not key.is_model_allowed(metric.model_name):
                    raise McpForbidden("Model '%s' out of scope" % metric.model_name)
                if not key.perm_read:
                    raise McpForbidden("perm_read missing")
                return self._content(metric.compute(env, arguments))

        # A custom tool is looked up before the built-ins so an administrator
        # can add one without worrying about colliding with a future built-in
        # (the `odoo_` prefix is reserved for ours, which keeps them apart).
        custom = self.env["mn.mcp.tool"].sudo().search([("name", "=", name)], limit=1)
        if custom:
            if not key.is_model_allowed(custom.model_name):
                raise McpForbidden("Model '%s' out of scope" % custom.model_name)
            if custom.kind in ("query", "group") and not key.perm_read:
                raise McpForbidden("perm_read missing")
            if custom.kind == "action" and not key.perm_write:
                raise McpForbidden("perm_write missing")
            return self._content(custom.run(env, arguments, self.max_records()))

        return self._builtin_call(key, env, name, arguments)

    def _builtin_call(self, key, env, name, a):  # noqa: C901 — a flat dispatch table
        model = a.get("model")
        limit_cap = self.max_records()

        def _check_model():
            if not model:
                raise McpForbidden("Missing 'model'")
            if not key.is_model_allowed(model):
                raise McpForbidden("Model '%s' out of scope" % model)
            if model not in env:
                raise McpForbidden("Model '%s' does not exist" % model)

        def _read():
            if not key.perm_read:
                raise McpForbidden("perm_read missing")

        # ── CRUD ──────────────────────────────────────────────────────
        if name == "odoo_search":
            _check_model(); _read()
            ids = env[model].search(
                a.get("domain") or [],
                limit=min(a.get("limit") or limit_cap, limit_cap),
                order=a.get("order")).ids
            return self._content({"ids": ids, "count": len(ids)})

        if name == "odoo_search_count":
            _check_model(); _read()
            return self._content({"count": env[model].search_count(a.get("domain") or [])})

        if name == "odoo_read":
            _check_model(); _read()
            data = env[model].browse(a.get("ids") or []).read(a.get("fields"))
            data = data[:limit_cap]
            return self._content({"records": data, "count": len(data)})

        if name == "odoo_search_read":
            _check_model(); _read()
            data = env[model].search_read(
                a.get("domain") or [], a.get("fields"),
                limit=min(a.get("limit") or limit_cap, limit_cap),
                order=a.get("order"))
            return self._content({"records": data, "count": len(data)})

        if name == "odoo_read_group":
            _check_model(); _read()
            groupby = a.get("groupby") or []
            aggregates = a.get("fields") or ["__count"]
            # `read_group` was removed in 19; `_read_group` returns tuples and
            # recordsets, so relational keys are unpacked into id + label —
            # serialised naively they become "res.country(233,)", which tells a
            # language model nothing.
            rows = env[model]._read_group(a.get("domain") or [],
                                          groupby=groupby, aggregates=aggregates)
            return self._content({
                "groups": [[_readable(cell) for cell in row] for row in rows],
                "groupby": groupby, "aggregates": aggregates})

        if name == "odoo_name_search":
            _check_model(); _read()
            return self._content(env[model].name_search(
                a.get("name") or "", limit=a.get("limit") or 8))

        if name == "odoo_create":
            _check_model()
            if not key.perm_create:
                raise McpForbidden("perm_create missing")
            return self._content({"id": env[model].create(a.get("values") or {}).id})

        if name == "odoo_create_many":
            _check_model()
            if not key.perm_create:
                raise McpForbidden("perm_create missing")
            return self._content({"ids": env[model].create(a.get("records") or []).ids})

        if name == "odoo_write":
            _check_model()
            if not key.perm_write:
                raise McpForbidden("perm_write missing")
            ok = env[model].browse(a.get("ids") or []).write(a.get("values") or {})
            return self._content({"ok": bool(ok)})

        if name == "odoo_unlink":
            _check_model()
            if not key.perm_unlink:
                raise McpForbidden("perm_unlink missing")
            return self._content({"ok": bool(env[model].browse(a.get("ids") or []).unlink())})

        if name == "odoo_copy":
            _check_model()
            if not key.perm_create:
                raise McpForbidden("perm_create missing")
            return self._content({"id": env[model].browse(a.get("id")).copy(
                default=a.get("default") or {}).id})

        if name == "odoo_find_or_create":
            _check_model(); _read()
            found = env[model].search(a.get("domain") or [], limit=1)
            if found:
                return self._content({"id": found.id, "created": False})
            if not key.perm_create:
                raise McpForbidden("perm_create missing")
            return self._content({"id": env[model].create(a.get("values") or {}).id,
                                  "created": True})

        # ── Discovery ─────────────────────────────────────────────────
        if name == "odoo_fields_get":
            _check_model(); _read()
            schema = env[model].fields_get(attributes=[
                "string", "type", "required", "help", "relation", "selection"])
            payload = {"model": model, "fields": schema}
            hint = self.env["mn.mcp.model.hint"].for_model(model)
            if hint:
                # The hint travels with the schema deliberately: a model that
                # calls fields_get is about to build a query, and that is the
                # moment the caveat is worth reading.
                payload["business_context"] = hint.to_dict()
            return self._content(payload)

        if name == "odoo_list_models":
            allowed = (key.allowed_models or "").strip()
            names = allowed.split(",") if allowed != "*" else ["*"]
            names = [n.strip() for n in names if n.strip()]
            hints = {h.model_name: h.summary for h in
                     self.env["mn.mcp.model.hint"].sudo().search(
                         [("model_name", "in", names)])}
            return self._content({
                "allowed": names,
                "described": [{"model": n, "summary": hints[n]}
                              for n in names if n in hints],
            })

        if name == "odoo_get_view":
            _check_model()
            try:
                return self._content(env[model].get_view(
                    view_type=a.get("view_type") or "form"))
            except Exception:  # noqa: BLE001 — a missing view is an answer, not a crash
                return self._content({"error": "view not found"})

        # ── Semantic layer ────────────────────────────────────────────
        if name == "odoo_describe_model":
            _check_model()
            hint = self.env["mn.mcp.model.hint"].for_model(model)
            if not hint:
                return self._content({
                    "model": model,
                    "summary": ("No business description has been written for "
                                "this model. Fall back to odoo_fields_get."),
                })
            return self._content(hint.to_dict())

        if name == "odoo_glossary":
            domain = [("active", "=", True)]
            term = (a.get("term") or "").strip()
            if term:
                domain += ["|", ("term", "ilike", term), ("synonyms", "ilike", term)]
            entries = self.env["mn.mcp.glossary"].sudo().search(domain, limit=200)
            # An entry pointing at a model this key cannot reach is noise at
            # best and a hint about data the caller may not see at worst.
            visible = [e for e in entries
                       if not e.model_name or key.is_model_allowed(e.model_name)]
            return self._content({"terms": [e.to_dict() for e in visible]})

        if name == "odoo_list_metrics":
            metrics = self.env["mn.mcp.metric"].sudo().search([])
            return self._content({"metrics": [{
                "name": "metric_%s" % m.name,
                "title": m.title or m.name,
                "description": m.description,
                "model": m.model_name,
                "unit": m.unit or "",
                "default_period": m.default_period,
            } for m in metrics if key.is_model_allowed(m.model_name)]})

        # ── Chatter / activities / mail ───────────────────────────────
        if name == "odoo_message_post":
            _check_model()
            if not key.perm_write:
                raise McpForbidden("perm_write missing")
            msg = env[model].browse(a.get("id")).message_post(
                body=a.get("body") or "", subject=a.get("subject"))
            return self._content({"message_id": msg.id})

        if name == "odoo_activity_schedule":
            _check_model()
            if not key.perm_write:
                raise McpForbidden("perm_write missing")
            record = env[model].browse(a.get("id"))
            vals = {"summary": a.get("summary") or "Follow-up",
                    "activity_type_id": env.ref("mail.mail_activity_data_todo").id}
            if a.get("date_deadline"):
                vals["date_deadline"] = a.get("date_deadline")
            if a.get("user_id"):
                vals["user_id"] = a.get("user_id")
            act = (record.activity_schedule(**vals)
                   if hasattr(record, "activity_schedule")
                   else env["mail.activity"].create({
                       **vals, "res_model": model, "res_id": record.id,
                       "res_model_id": env["ir.model"]._get(model).id}))
            aid = act.id if hasattr(act, "id") else (act[0].id if act else 0)
            return self._content({"activity_id": aid})

        if name == "odoo_send_email":
            tmpl = env["mail.template"].browse(a.get("template_id"))
            if not tmpl.exists():
                raise McpForbidden("Template %s not found" % a.get("template_id"))
            tmpl.send_mail(
                a.get("id"), force_send=True,
                email_values={"email_to": a.get("email_to")} if a.get("email_to") else None)
            return self._content({"ok": True})

        # ── Reports & attachments ─────────────────────────────────────
        if name == "odoo_print_report":
            rendered = env["ir.actions.report"]._render_qweb_pdf(
                a.get("report_name"), a.get("ids") or [])
            pdf = rendered[0] if isinstance(rendered, tuple) else rendered
            return self._content({
                "filename": "%s.pdf" % a.get("report_name"),
                "mimetype": "application/pdf",
                "datas_b64": base64.b64encode(pdf).decode() if pdf else "",
            })

        if name == "odoo_attach_file":
            _check_model()
            if not key.perm_create:
                raise McpForbidden("perm_create missing")
            att = env["ir.attachment"].create({
                "name": a.get("name") or "file.bin",
                "res_model": model, "res_id": a.get("id"),
                "datas": a.get("datas") or "",
                "mimetype": a.get("mimetype") or "application/octet-stream",
            })
            return self._content({"attachment_id": att.id})

        # ── Server action / generic execute ───────────────────────────
        if name == "odoo_run_server_action":
            action = env["ir.actions.server"].browse(a.get("action_id"))
            if not action.exists():
                raise McpForbidden("Server action %s not found" % a.get("action_id"))
            res = action.with_context(
                active_model=a.get("model"), active_ids=a.get("ids") or [],
                active_id=(a.get("ids") or [None])[0]).run()
            return self._content({"ok": True, "result": res})

        if name == "odoo_execute":
            _check_model()
            method = a.get("method") or ""
            if not key.is_method_allowed(method):
                raise McpForbidden("Method '%s' not in allowed_methods" % method)
            res = getattr(env[model], method)(*(a.get("args") or []),
                                              **(a.get("kwargs") or {}))
            return self._content(res)

        # ── Discovery / helpers ───────────────────────────────────────
        if name == "odoo_menu_tree":
            def walk(menu, depth=0):
                return {"id": menu.id, "name": menu.name, "depth": depth,
                        "children": [walk(c, depth + 1) for c in menu.child_id[:25]]}
            roots = env["ir.ui.menu"].search([("parent_id", "=", False)], limit=50)
            return self._content([walk(m) for m in roots])

        if name == "odoo_user_context":
            user = env.user
            return self._content({
                "id": user.id, "name": user.name, "login": user.login,
                "email": user.email, "company": user.company_id.name,
                "lang": user.lang, "tz": user.tz,
                # Renamed from groups_id in 19.0.
                "groups": user.group_ids.mapped("name")[:20],
            })

        raise McpForbidden("Unknown tool '%s'" % name)

    # ─────────────────────────────────────────────────────────────────
    def _content(self, payload):
        """Wrap a result as MCP tool content.

        Text is what every revision understands; structuredContent is what a
        client uses when the tool declared an outputSchema. Sending both means
        one code path serves an old client and a new one.
        """
        try:
            text = json.dumps(payload, default=str)
        except Exception:  # noqa: BLE001
            text = str(payload)
        out = {"content": [{"type": "text", "text": text}]}
        if isinstance(payload, dict):
            out["structuredContent"] = json.loads(json.dumps(payload, default=str))
        return out

    # ─────────────────────────────────────────────────────────────────
    # resources
    # ─────────────────────────────────────────────────────────────────
    @api.model
    def resource_templates(self, params=None):
        """URI patterns a client can fill in, rather than a fixed list.

        A list of every record in the database would be useless and enormous.
        A template says "you may ask for odoo://record/{model}/{id}" and lets
        the client construct the one it wants.
        """
        templates = [
            {"uriTemplate": "odoo://model/{model}",
             "name": "Model schema",
             "description": "Field schema plus any business description.",
             "mimeType": "application/json"},
            {"uriTemplate": "odoo://record/{model}/{id}",
             "name": "One record",
             "description": "Every readable field of a single record.",
             "mimeType": "application/json"},
            {"uriTemplate": "odoo://search/{model}?domain={domain}",
             "name": "Search result",
             "description": "Records matching a domain, as JSON.",
             "mimeType": "application/json"},
            {"uriTemplate": "odoo://metric/{name}",
             "name": "Business metric",
             "description": "A named, pre-approved number.",
             "mimeType": "application/json"},
            {"uriTemplate": "odoo://report/{report_name}/{id}",
             "name": "PDF report",
             "description": "A rendered QWeb report.",
             "mimeType": "application/pdf"},
            {"uriTemplate": "odoo://attachment/{id}",
             "name": "Attachment",
             "description": "A stored file.",
             "mimeType": "application/octet-stream"},
        ]
        return _paginate({"resourceTemplates": templates}, "resourceTemplates", params)

    @api.model
    def resources_list(self, key, params=None):
        allowed = (key.allowed_models or "").strip()
        models_ = (allowed.split(",") if allowed != "*"
                   else ["res.partner", "product.template", "sale.order"])
        hints = {h.model_name: h.summary for h in
                 self.env["mn.mcp.model.hint"].sudo().search([])}
        resources = [{
            "uri": "odoo://model/%s" % m.strip(),
            "name": m.strip(),
            "description": hints.get(m.strip(), "Schema of %s" % m.strip()),
            "mimeType": "application/json",
        } for m in models_ if m.strip()]

        resources.append({
            "uri": "odoo://glossary",
            "name": "Business glossary",
            "description": "What this company means by its own terms.",
            "mimeType": "application/json"})
        for metric in self.env["mn.mcp.metric"].sudo().search([]):
            if key.is_model_allowed(metric.model_name):
                resources.append({
                    "uri": "odoo://metric/%s" % metric.name,
                    "name": metric.title or metric.name,
                    "description": metric.description,
                    "mimeType": "application/json"})
        return _paginate({"resources": resources}, "resources", params)

    @api.model
    def resources_read(self, key, env, params):  # noqa: C901 — flat URI table
        uri = (params.get("uri") or "").strip()

        def _json(payload, mime="application/json"):
            return {"contents": [{"uri": uri, "mimeType": mime,
                                  "text": json.dumps(payload, default=str)}]}

        if uri == "odoo://glossary":
            entries = self.env["mn.mcp.glossary"].sudo().search([("active", "=", True)])
            return _json({"terms": [e.to_dict() for e in entries
                                    if not e.model_name or key.is_model_allowed(e.model_name)]})

        if uri.startswith("odoo://metric/"):
            metric = self.env["mn.mcp.metric"].sudo().search(
                [("name", "=", uri[len("odoo://metric/"):])], limit=1)
            if not metric:
                raise McpForbidden("Unknown metric in '%s'" % uri)
            if not key.is_model_allowed(metric.model_name) or not key.perm_read:
                raise McpForbidden("Metric '%s' out of scope" % metric.name)
            return _json(metric.compute(env, {}))

        if uri.startswith("odoo://model/"):
            model = uri[len("odoo://model/"):].strip()
            self._guard_model(key, env, model)
            payload = {"model": model,
                       "fields": env[model].fields_get(
                           attributes=["string", "type", "required", "help"])}
            hint = self.env["mn.mcp.model.hint"].for_model(model)
            if hint:
                payload["business_context"] = hint.to_dict()
            return _json(payload)

        if uri.startswith("odoo://record/"):
            rest = uri[len("odoo://record/"):].strip("/")
            parts = rest.split("/")
            if len(parts) != 2 or not parts[1].isdigit():
                raise McpForbidden("Expected odoo://record/{model}/{id}")
            model, rec_id = parts[0], int(parts[1])
            self._guard_model(key, env, model)
            record = env[model].browse(rec_id)
            if not record.exists():
                raise McpForbidden("Record %s/%s not found" % (model, rec_id))
            return _json({"model": model, "id": rec_id, "record": record.read()[0]})

        if uri.startswith("odoo://search/"):
            rest = uri[len("odoo://search/"):]
            model, _sep, query = rest.partition("?")
            self._guard_model(key, env, model.strip())
            domain = []
            if query.startswith("domain="):
                from urllib.parse import unquote
                try:
                    domain = json.loads(unquote(query[len("domain="):]))
                except Exception:  # noqa: BLE001
                    raise McpForbidden("The domain in that URI is not valid JSON")
            if not isinstance(domain, list):
                raise McpForbidden("A domain must be a list")
            rows = env[model.strip()].search_read(domain, limit=self.max_records())
            return _json({"model": model.strip(), "count": len(rows), "records": rows})

        if uri.startswith("odoo://attachment/"):
            att_id = uri[len("odoo://attachment/"):].strip()
            if not att_id.isdigit():
                raise McpForbidden("Expected odoo://attachment/{id}")
            att = env["ir.attachment"].browse(int(att_id))
            if not att.exists():
                raise McpForbidden("Attachment %s not found" % att_id)
            # Attachments carry the record's data, so the key's whitelist has
            # to cover the model the file hangs off — otherwise a scoped key
            # reads anything by guessing attachment ids.
            if att.res_model:
                self._guard_model(key, env, att.res_model)
            return {"contents": [{"uri": uri,
                                  "mimeType": att.mimetype or "application/octet-stream",
                                  "blob": att.datas.decode() if att.datas else ""}]}

        if uri.startswith("odoo://report/"):
            rest = uri[len("odoo://report/"):].strip("/")
            parts = rest.rsplit("/", 1)
            if len(parts) != 2 or not parts[1].isdigit():
                raise McpForbidden("Expected odoo://report/{report_name}/{id}")
            rendered = env["ir.actions.report"]._render_qweb_pdf(parts[0], [int(parts[1])])
            pdf = rendered[0] if isinstance(rendered, tuple) else rendered
            return {"contents": [{"uri": uri, "mimeType": "application/pdf",
                                  "blob": base64.b64encode(pdf).decode() if pdf else ""}]}

        raise McpForbidden("Unknown resource '%s'" % uri)

    def _guard_model(self, key, env, model):
        if not key.is_model_allowed(model):
            raise McpForbidden("Model '%s' out of scope" % model)
        if model not in env:
            raise McpForbidden("Model '%s' does not exist" % model)
        if not key.perm_read:
            raise McpForbidden("perm_read missing")

    # ─────────────────────────────────────────────────────────────────
    # prompts
    # ─────────────────────────────────────────────────────────────────
    @api.model
    def prompts_list(self, params=None):
        prompts = self.env["mn.mcp.prompt"].sudo().search([("active", "=", True)])
        return _paginate({"prompts": [p.to_mcp() for p in prompts]}, "prompts", params)

    @api.model
    def prompts_get(self, params):
        name = params.get("name")
        prompt = self.env["mn.mcp.prompt"].sudo().search(
            [("name", "=", name), ("active", "=", True)], limit=1)
        if not prompt:
            raise McpForbidden("Prompt '%s' not found" % name)
        return {"description": prompt.title or name,
                "messages": [{"role": "user",
                              "content": {"type": "text",
                                          "text": prompt.render(params.get("arguments") or {})}}]}


# ─────────────────────────────────────────────────────────────────────
def _readable(value):
    """Make a _read_group cell safe and meaningful in JSON."""
    if isinstance(value, models.BaseModel):
        return {"id": value.id, "name": value.display_name} if value else None
    return value


def _paginate(result, list_key, params):
    """Opaque-cursor pagination, as the spec requires.

    The cursor is just the offset, but it is base64-wrapped because the spec
    says clients must not interpret it — publishing a bare integer invites
    somebody to do arithmetic on it, and then the format can never change.
    """
    items = result.get(list_key) or []
    offset = 0
    cursor = (params or {}).get("cursor")
    if cursor:
        try:
            offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
        except Exception:  # noqa: BLE001
            offset = 0
    page = items[offset:offset + PAGE_SIZE]
    result[list_key] = page
    if offset + PAGE_SIZE < len(items):
        result["nextCursor"] = base64.urlsafe_b64encode(
            str(offset + PAGE_SIZE).encode()).decode()
    return result
