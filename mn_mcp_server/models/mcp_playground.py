# -*- coding: utf-8 -*-
"""The playground — call a tool from inside Odoo, exactly as Claude would.

Every connector has the same failure mode: the administrator configures it,
hands the URL to a colleague, and finds out three days later that the key was
missing a permission or the custom tool's domain was wrong. The feedback loop
runs through somebody else's chat window, which is the worst debugger ever
built.

So this runs the call here. It picks a real API key, goes through
``mn.mcp.engine`` — the same dispatch the HTTP endpoint uses — and shows the
result, the latency, and the audit row it produced.

Two decisions worth stating:

* It does **not** bypass the guard rails. Run ``odoo_unlink`` here and you get
  the same confirmation request a client would, because a test button that is
  more permissive than production tests the wrong thing.
* It runs as the **key's** user, not as you. An administrator testing a
  restricted key needs to see what that key sees, not what an administrator
  sees. This is the whole point: it is the misconfiguration you are hunting.
"""
import json
import time

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .mcp_engine import McpForbidden

METHODS = [
    ("tools/call", "Call a tool"),
    ("tools/list", "List tools"),
    ("resources/list", "List resources"),
    ("resources/templates/list", "List resource templates"),
    ("resources/read", "Read a resource"),
    ("prompts/list", "List prompts"),
    ("prompts/get", "Get a prompt"),
    ("server/discover", "Discover (unauthenticated)"),
]


class McpPlayground(models.TransientModel):
    _name = "mn.mcp.playground"
    _description = "MCP Playground"

    api_key_id = fields.Many2one(
        "mn.mcp.api_key", string="Run as key", required=True,
        domain=[("state", "=", "active")],
        default=lambda s: s.env["mn.mcp.api_key"].search(
            [("state", "=", "active")], limit=1),
        help="The call runs with this key's user, models and permissions — "
             "not yours. That is the point.")
    key_user_id = fields.Many2one(related="api_key_id.user_id", string="Acting as")
    key_models = fields.Char(related="api_key_id.allowed_models", string="Scope")

    method = fields.Selection(METHODS, default="tools/call", required=True)
    tool_name = fields.Char(string="Tool")
    tool_id = fields.Many2one("mn.mcp.tool.choice", string="Pick a tool")
    arguments = fields.Text(default="{}", string="Arguments (JSON)")
    uri = fields.Char(string="Resource URI", help="e.g. odoo://model/res.partner")
    prompt_name = fields.Char(string="Prompt name")

    protocol_version = fields.Selection(
        [("2026-07-28", "2026-07-28 (current)"),
         ("2025-11-25", "2025-11-25"),
         ("2025-06-18", "2025-06-18"),
         ("2025-03-26", "2025-03-26"),
         ("2024-11-05", "2024-11-05 (legacy)")],
        default="2026-07-28", required=True,
        help="Answer as this revision would. Useful for checking that an old "
             "client still gets a shape it understands.")

    result = fields.Text(readonly=True)
    latency_ms = fields.Integer(readonly=True)
    status = fields.Selection([("ok", "OK"), ("refused", "Refused"),
                               ("error", "Error"), ("confirm", "Confirmation required")],
                              readonly=True)
    curl_command = fields.Text(string="Same call as curl", compute="_compute_curl")

    @api.depends("method")
    def _compute_display_name(self):
        # A transient with no name field puts "mn.mcp.playground,1" in the
        # breadcrumb, which is the kind of detail that makes a product feel
        # unfinished.
        for record in self:
            record.display_name = _("MCP Playground")

    # ------------------------------------------------------------------
    @api.onchange("tool_id")
    def _onchange_tool_id(self):
        """Fill the name and a skeleton of required arguments."""
        if not self.tool_id:
            return
        self.tool_name = self.tool_id.name
        schema = json.loads(self.tool_id.input_schema or "{}")
        skeleton = {}
        for field_name in schema.get("required") or []:
            spec = (schema.get("properties") or {}).get(field_name) or {}
            skeleton[field_name] = _placeholder(spec.get("type"))
        self.arguments = json.dumps(skeleton, indent=2)

    @api.depends("method", "tool_name", "arguments", "api_key_id", "uri", "prompt_name")
    def _compute_curl(self):
        for rec in self:
            body = rec._rpc_body()
            url = rec.api_key_id.connect_url or "/mcp"
            rec.curl_command = (
                "curl -s -X POST %s \\\n"
                "  -H 'Content-Type: application/json' \\\n"
                "  -H 'Authorization: Bearer YOUR-TOKEN' \\\n"
                "  -H 'MCP-Protocol-Version: %s' \\\n"
                "  -d '%s'"
            ) % (url, rec.protocol_version, json.dumps(body))

    def _rpc_body(self):
        """The JSON-RPC envelope this form describes — shown, then executed."""
        self.ensure_one()
        params = {}
        if self.method == "tools/call":
            params = {"name": self.tool_name or "",
                      "arguments": self._parsed_arguments(strict=False)}
        elif self.method == "resources/read":
            params = {"uri": self.uri or ""}
        elif self.method == "prompts/get":
            params = {"name": self.prompt_name or "",
                      "arguments": self._parsed_arguments(strict=False)}
        return {"jsonrpc": "2.0", "id": 1, "method": self.method, "params": params}

    def _parsed_arguments(self, strict=True):
        raw = (self.arguments or "").strip() or "{}"
        try:
            parsed = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            if strict:
                raise UserError(_("Arguments are not valid JSON: %s", exc))
            return {}
        if not isinstance(parsed, dict):
            if strict:
                raise UserError(_("Arguments must be a JSON object."))
            return {}
        return parsed

    # ------------------------------------------------------------------
    def action_run(self):
        self.ensure_one()
        from ..controllers import protocol as P
        from ..controllers.mcp import SERVER_VERSION

        key = self.api_key_id
        if not key or key.state != "active":
            raise UserError(_("Pick an active API key."))

        # Validate the JSON here, not in _rpc_body: that one is also used by the
        # live curl preview, which must keep rendering while you are mid-edit
        # rather than throwing a dialog at every keystroke.
        if self.method in ("tools/call", "prompts/get"):
            self._parsed_arguments(strict=True)

        body = self._rpc_body()
        params = body["params"]
        Engine = self.env["mn.mcp.engine"].sudo()
        # The engine runs as the key's user so record rules and ACLs bite
        # exactly as they would over the wire.
        user_env = self.env(user=key.user_id.id, su=False)

        start = time.time()
        status, payload = "ok", None
        try:
            if self.method == "server/discover":
                payload = P.discover(SERVER_VERSION)
            elif self.method == "tools/list":
                payload = Engine.tools_list(params)
            elif self.method == "tools/call":
                if not self.tool_name:
                    raise UserError(_("Which tool?"))
                payload = Engine.tools_call(key, user_env, params)
                if isinstance(payload, dict) and payload.get("resultType") == "input_required":
                    status = "confirm"
            elif self.method == "resources/list":
                payload = Engine.resources_list(key, params)
            elif self.method == "resources/templates/list":
                payload = Engine.resource_templates(params)
            elif self.method == "resources/read":
                payload = Engine.resources_read(key, user_env, params)
            elif self.method == "prompts/list":
                payload = Engine.prompts_list(params)
            elif self.method == "prompts/get":
                payload = Engine.prompts_get(params)
            payload = P.decorate_result(payload, self.protocol_version,
                                        self.method, SERVER_VERSION)
        except McpForbidden as exc:
            status, payload = "refused", {"error": {"code": P.ERR_FORBIDDEN,
                                                    "message": str(exc)}}
        except UserError:
            raise
        except Exception as exc:  # noqa: BLE001 — the playground reports, never crashes
            status, payload = "error", {"error": {"code": P.ERR_INTERNAL,
                                                  "message": str(exc)}}

        latency = int((time.time() - start) * 1000)
        self.env["mn.mcp.audit"].sudo().log(
            api_key_id=key.id, method="playground:%s" % self.method,
            status="ok" if status in ("ok", "confirm") else
                   ("forbidden" if status == "refused" else "error"),
            latency_ms=latency, args=params,
            tool_name=params.get("name"),
            model_target=(params.get("arguments") or {}).get("model"),
        )

        self.write({
            "result": json.dumps(payload, indent=2, default=str),
            "latency_ms": latency,
            "status": status,
        })
        # Stay on the same record so the result appears in place; returning a
        # fresh action would reload the form and lose the arguments you typed.
        return True


class McpToolChoice(models.Model):
    """A flat list of callable tool names, so the playground can offer a picker.

    Tool definitions are computed — built-ins in code, custom tools and metrics
    in their own models — and a Many2one cannot point at a computed list. This
    mirrors them into rows, refreshed whenever the playground is opened. It is
    a UI convenience and nothing dispatches through it.
    """

    _name = "mn.mcp.tool.choice"
    _description = "MCP tool (picker)"
    _order = "name"

    name = fields.Char(required=True, index=True)
    description = fields.Text()
    kind = fields.Selection([("builtin", "Built-in"), ("custom", "Custom"),
                             ("metric", "Metric")], default="builtin")
    read_only = fields.Boolean()
    input_schema = fields.Text()

    _name_uniq = models.Constraint("unique(name)", "Duplicate tool name.")

    @api.model
    def refresh(self):
        """Re-mirror the live tool list. Cheap, and always current."""
        tools = self.env["mn.mcp.engine"].sudo().tools_list({}).get("tools") or []
        existing = {r.name: r for r in self.sudo().search([])}
        seen = set()
        for tool in tools:
            name = tool["name"]
            seen.add(name)
            vals = {
                "name": name,
                "description": tool.get("description") or "",
                "kind": ("metric" if name.startswith("metric_")
                         else "builtin" if name.startswith("odoo_") else "custom"),
                "read_only": (tool.get("annotations") or {}).get("readOnlyHint", False),
                "input_schema": json.dumps(tool.get("inputSchema") or {}),
            }
            if name in existing:
                existing[name].sudo().write(vals)
            else:
                self.sudo().create(vals)
        stale = [r for n, r in existing.items() if n not in seen]
        for record in stale:
            record.sudo().unlink()
        return True

    @api.model
    def action_open_playground(self):
        """Menu action: refresh the picker, then open a fresh playground."""
        self.refresh()
        record = self.env["mn.mcp.playground"].create({})
        return {
            "type": "ir.actions.act_window",
            "name": _("MCP Playground"),
            "res_model": "mn.mcp.playground",
            "res_id": record.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }


def _placeholder(json_type):
    return {"string": "", "integer": 0, "number": 0,
            "boolean": False, "array": [], "object": {}}.get(json_type, "")
