# -*- coding: utf-8 -*-
"""Tests for the v4 wave: semantic layer, structured output, resources,
streaming, playground and self-service keys.

The interesting assertions here are not "does the feature work" — they are the
ways each one could quietly widen access: a metric reaching a model the key
cannot see, a resource URI walking to another model, a portal user posting
permissions into their own key, a playground that runs as the administrator
instead of as the key.
"""
import json

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged


class _KeyMixin:
    @classmethod
    def _make_key(cls, **overrides):
        vals = {
            "name": "advanced-test",
            "user_id": cls.env.ref("base.user_admin").id,
            "allow_all_models": True,
            "perm_read": True, "perm_write": True,
            "perm_create": True, "perm_unlink": True,
        }
        vals.update(overrides)
        return cls.env["mn.mcp.api_key"].create(vals)


@tagged("post_install", "-at_install")
class TestSemanticLayer(TransactionCase, _KeyMixin):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key = cls._make_key()
        cls.engine = cls.env["mn.mcp.engine"]
        cls.partner_model = cls.env["ir.model"]._get("res.partner")
        cls.env["res.partner"].create([
            {"name": "Metric A", "partner_latitude": 100},
            {"name": "Metric B", "partner_latitude": 300},
        ])

    def _metric(self, **overrides):
        vals = {
            "name": "test_credit",
            "description": "Total credit limit across partners.",
            "model_id": self.partner_model.id,
            "aggregate": "sum",
            "measure_field": "partner_latitude",
            "domain": "[('name', 'like', 'Metric ')]",
        }
        vals.update(overrides)
        return self.env["mn.mcp.metric"].create(vals)

    # ── metrics ──────────────────────────────────────────────────────
    def test_metric_computes_the_number(self):
        metric = self._metric()
        out = metric.compute(self.env, {})
        self.assertEqual(out["value"], 400)
        self.assertEqual(out["record_count"], 2)

    def test_metric_appears_as_a_tool(self):
        self._metric()
        names = [t["name"] for t in self.engine.tools_list({})["tools"]]
        self.assertIn("metric_test_credit", names)

    def test_metric_declares_an_output_schema(self):
        schema = self._metric().to_schema()
        self.assertIn("outputSchema", schema)
        self.assertTrue(schema["annotations"]["readOnlyHint"])

    def test_metric_extra_domain_narrows_only(self):
        """An extra domain is ANDed on, so it can filter but never widen."""
        metric = self._metric()
        out = metric.compute(self.env, {"extra_domain": [("name", "=", "Metric A")]})
        self.assertEqual(out["value"], 100)

    def test_metric_out_of_scope_is_refused(self):
        """A key that cannot see the model cannot reach it through a metric."""
        from ..models.mcp_engine import McpForbidden
        self._metric()
        narrow = self._make_key(name="narrow", allow_all_models=False,
                                allowed_model_ids=[(6, 0, [
                                    self.env["ir.model"]._get("res.users").id])])
        with self.assertRaises(McpForbidden):
            self.engine.tools_call(narrow, self.env, {
                "name": "metric_test_credit", "arguments": {}})

    def test_metric_groupby_returns_a_breakdown(self):
        metric = self._metric(name="test_by_partner", groupby="name")
        out = metric.compute(self.env, {})
        self.assertEqual(len(out["breakdown"]), 2)
        self.assertEqual(out["value"], 400)

    def test_metric_rejects_a_broken_domain(self):
        with self.assertRaises(ValidationError):
            self._metric(name="broken", domain="[(this is not a domain")

    def test_metric_rejects_an_aggregate_without_a_field(self):
        with self.assertRaises(ValidationError):
            self._metric(name="nofield", aggregate="sum", measure_field=False)

    def test_metric_name_must_be_client_safe(self):
        with self.assertRaises(ValidationError):
            self._metric(name="Not.A.Valid.Name")

    def test_period_needs_a_date_field(self):
        with self.assertRaises(ValidationError):
            self._metric(name="dated", default_period="this_month", date_field=False)

    # ── glossary ─────────────────────────────────────────────────────
    def test_glossary_tool_returns_definitions(self):
        self.env["mn.mcp.glossary"].create({
            "term": "Churn", "definition": "A customer who stopped paying."})
        out = self.engine.tools_call(self.key, self.env, {
            "name": "odoo_glossary", "arguments": {}})
        terms = out["structuredContent"]["terms"]
        self.assertIn("Churn", [t["term"] for t in terms])

    def test_glossary_hides_entries_for_models_out_of_scope(self):
        self.env["mn.mcp.glossary"].create({
            "term": "Secret", "definition": "Only on res.users.",
            "model_id": self.env["ir.model"]._get("res.users").id})
        narrow = self._make_key(name="no-users", allow_all_models=False,
                                allowed_model_ids=[(6, 0, [self.partner_model.id])])
        out = self.engine.tools_call(narrow, self.env, {
            "name": "odoo_glossary", "arguments": {}})
        self.assertNotIn("Secret",
                         [t["term"] for t in out["structuredContent"]["terms"]])

    def test_glossary_search_matches_a_synonym(self):
        self.env["mn.mcp.glossary"].create({
            "term": "Churn", "definition": "Lost customer.",
            "synonyms": "attrition, lapsed"})
        out = self.engine.tools_call(self.key, self.env, {
            "name": "odoo_glossary", "arguments": {"term": "attrition"}})
        self.assertEqual(len(out["structuredContent"]["terms"]), 1)

    # ── model hints ──────────────────────────────────────────────────
    def test_hint_rides_along_with_fields_get(self):
        self.env["mn.mcp.model.hint"].create({
            "model_id": self.partner_model.id,
            "summary": "Everyone we deal with.",
            "caveats": "Companies and contacts live in the same table."})
        out = self.engine.tools_call(self.key, self.env, {
            "name": "odoo_fields_get", "arguments": {"model": "res.partner"}})
        context = out["structuredContent"]["business_context"]
        self.assertEqual(context["summary"], "Everyone we deal with.")

    def test_describe_model_says_so_when_nothing_is_written(self):
        out = self.engine.tools_call(self.key, self.env, {
            "name": "odoo_describe_model", "arguments": {"model": "res.partner"}})
        self.assertIn("No business description",
                      out["structuredContent"]["summary"])

    def test_one_hint_per_model(self):
        from psycopg2 import IntegrityError
        from odoo.tools import mute_logger
        self.env["mn.mcp.model.hint"].create({
            "model_id": self.partner_model.id, "summary": "First."})
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            with self.env.cr.savepoint():
                self.env["mn.mcp.model.hint"].create({
                    "model_id": self.partner_model.id, "summary": "Second."})


@tagged("post_install", "-at_install")
class TestStructuredOutput(TransactionCase, _KeyMixin):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key = cls._make_key()
        cls.engine = cls.env["mn.mcp.engine"]

    def test_search_returns_structured_content(self):
        out = self.engine.tools_call(self.key, self.env, {
            "name": "odoo_search",
            "arguments": {"model": "res.partner", "limit": 3}})
        self.assertIn("structuredContent", out)
        self.assertIn("ids", out["structuredContent"])
        # The text block still carries the same payload, so a client that
        # predates structuredContent loses nothing.
        self.assertEqual(json.loads(out["content"][0]["text"])["ids"],
                         out["structuredContent"]["ids"])

    def test_every_declared_output_schema_is_an_object(self):
        for tool in self.engine.tools_list({})["tools"]:
            if "outputSchema" in tool:
                self.assertEqual(tool["outputSchema"]["type"], "object",
                                 "%s declares a non-object output" % tool["name"])

    def test_read_returns_records_matching_its_schema(self):
        partner = self.env["res.partner"].create({"name": "Structured"})
        out = self.engine.tools_call(self.key, self.env, {
            "name": "odoo_read",
            "arguments": {"model": "res.partner", "ids": [partner.id],
                          "fields": ["name"]}})
        self.assertEqual(out["structuredContent"]["count"], 1)
        self.assertEqual(out["structuredContent"]["records"][0]["name"], "Structured")

    def test_read_group_unpacks_relational_keys(self):
        """A recordset serialised naively reads as res.country(233,) — useless."""
        self.env["res.partner"].create({"name": "Grouped", "country_id":
                                        self.env.ref("base.be").id})
        out = self.engine.tools_call(self.key, self.env, {
            "name": "odoo_read_group",
            "arguments": {"model": "res.partner", "groupby": ["country_id"],
                          "fields": ["__count"]}})
        groups = out["structuredContent"]["groups"]
        keys = [g[0] for g in groups if g[0]]
        self.assertTrue(all(isinstance(k, dict) and "name" in k for k in keys))

    def test_user_context_reads_groups_on_19(self):
        """groups_id was renamed group_ids; this tool used to crash on it."""
        out = self.engine.tools_call(self.key, self.env, {
            "name": "odoo_user_context", "arguments": {}})
        self.assertIn("groups", out["structuredContent"])


@tagged("post_install", "-at_install")
class TestResources(TransactionCase, _KeyMixin):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key = cls._make_key()
        cls.engine = cls.env["mn.mcp.engine"]

    def _read(self, uri):
        return self.engine.resources_read(self.key, self.env, {"uri": uri})

    def test_templates_are_listed(self):
        uris = [t["uriTemplate"]
                for t in self.engine.resource_templates({})["resourceTemplates"]]
        self.assertIn("odoo://record/{model}/{id}", uris)

    def test_record_uri_reads_one_record(self):
        partner = self.env["res.partner"].create({"name": "Resource"})
        payload = json.loads(self._read(
            "odoo://record/res.partner/%s" % partner.id)["contents"][0]["text"])
        self.assertEqual(payload["record"]["name"], "Resource")

    def test_record_uri_respects_the_model_whitelist(self):
        from ..models.mcp_engine import McpForbidden
        narrow = self._make_key(name="partners-only", allow_all_models=False,
                                allowed_model_ids=[(6, 0, [
                                    self.env["ir.model"]._get("res.partner").id])])
        with self.assertRaises(McpForbidden):
            self.engine.resources_read(narrow, self.env,
                                       {"uri": "odoo://record/res.users/1"})

    def test_search_uri_applies_the_domain(self):
        self.env["res.partner"].create({"name": "URI Search Target"})
        from urllib.parse import quote
        domain = quote(json.dumps([["name", "=", "URI Search Target"]]))
        payload = json.loads(self._read(
            "odoo://search/res.partner?domain=%s" % domain)["contents"][0]["text"])
        self.assertEqual(payload["count"], 1)

    def test_search_uri_rejects_a_domain_that_is_not_json(self):
        from ..models.mcp_engine import McpForbidden
        with self.assertRaises(McpForbidden):
            self._read("odoo://search/res.partner?domain=not-json")

    def test_metric_uri_returns_the_number(self):
        self.env["mn.mcp.metric"].create({
            "name": "uri_metric", "description": "Count of partners.",
            "model_id": self.env["ir.model"]._get("res.partner").id,
            "aggregate": "count"})
        payload = json.loads(self._read("odoo://metric/uri_metric")["contents"][0]["text"])
        self.assertEqual(payload["metric"], "uri_metric")

    def test_unknown_uri_is_refused(self):
        from ..models.mcp_engine import McpForbidden
        with self.assertRaises(McpForbidden):
            self._read("odoo://nonsense/1")

    def test_attachment_uri_is_scoped_to_its_record(self):
        """Guessing attachment ids must not read past the key's whitelist."""
        from ..models.mcp_engine import McpForbidden
        user = self.env.ref("base.user_admin")
        att = self.env["ir.attachment"].create({
            "name": "secret.txt", "res_model": "res.users", "res_id": user.id,
            "datas": "aGVsbG8="})
        narrow = self._make_key(name="partners-only-2", allow_all_models=False,
                                allowed_model_ids=[(6, 0, [
                                    self.env["ir.model"]._get("res.partner").id])])
        with self.assertRaises(McpForbidden):
            self.engine.resources_read(narrow, self.env,
                                       {"uri": "odoo://attachment/%s" % att.id})

    def test_list_pagination_hands_back_an_opaque_cursor(self):
        from ..models.mcp_engine import _paginate, PAGE_SIZE
        items = [{"name": "t%s" % i} for i in range(PAGE_SIZE + 5)]
        first = _paginate({"tools": list(items)}, "tools", {})
        self.assertEqual(len(first["tools"]), PAGE_SIZE)
        self.assertTrue(first["nextCursor"])
        # The cursor must not be a number a client could do arithmetic on.
        self.assertFalse(first["nextCursor"].isdigit())
        second = _paginate({"tools": list(items)}, "tools",
                           {"cursor": first["nextCursor"]})
        self.assertEqual(len(second["tools"]), 5)
        self.assertNotIn("nextCursor", second)

    def test_a_garbage_cursor_starts_from_the_beginning(self):
        from ..models.mcp_engine import _paginate
        out = _paginate({"tools": [{"name": "a"}]}, "tools", {"cursor": "!!!"})
        self.assertEqual(len(out["tools"]), 1)


@tagged("post_install", "-at_install")
class TestStreaming(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key = cls.env["mn.mcp.api_key"].create({
            "name": "sse-test", "user_id": cls.env.ref("base.user_admin").id,
            "allow_all_models": True, "perm_read": True})
        cls.token = cls.key.token

    def _post(self, body, accept):
        return self.url_open("/mcp", data=json.dumps(body), headers={
            "Content-Type": "application/json",
            "Accept": accept,
            "Authorization": "Bearer %s" % self.token})

    def test_sse_framing_when_the_client_asks_for_it(self):
        response = self._post(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            "text/event-stream")
        self.assertIn("text/event-stream", response.headers["Content-Type"])
        self.assertTrue(response.text.startswith("event: message\ndata: "))
        payload = json.loads(response.text.split("data: ", 1)[1].strip())
        self.assertIn("tools", payload["result"])

    def test_plain_json_when_it_does_not(self):
        response = self._post(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            "application/json")
        self.assertIn("application/json", response.headers["Content-Type"])
        self.assertIn("tools", response.json()["result"])

    def test_resource_templates_over_the_wire(self):
        response = self._post({"jsonrpc": "2.0", "id": 1,
                               "method": "resources/templates/list", "params": {}},
                              "application/json")
        self.assertTrue(response.json()["result"]["resourceTemplates"])


@tagged("post_install", "-at_install")
class TestPlayground(TransactionCase, _KeyMixin):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key = cls._make_key(perm_unlink=False)

    def _pg(self, **vals):
        vals.setdefault("api_key_id", self.key.id)
        return self.env["mn.mcp.playground"].create(vals)

    def test_it_runs_a_tool_and_reports_latency(self):
        pg = self._pg(method="tools/call", tool_name="odoo_search",
                      arguments=json.dumps({"model": "res.partner", "limit": 2}))
        pg.action_run()
        self.assertEqual(pg.status, "ok")
        self.assertIn("ids", pg.result)

    def test_it_reports_a_refusal_instead_of_crashing(self):
        pg = self._pg(method="tools/call", tool_name="odoo_unlink",
                      arguments=json.dumps({"model": "res.partner", "ids": [1],
                                            "confirm": True}))
        pg.action_run()
        self.assertEqual(pg.status, "refused")
        self.assertIn("perm_unlink", pg.result)

    def test_it_does_not_bypass_the_confirmation_guard(self):
        """A test button more permissive than production tests nothing."""
        key = self._make_key(name="deleter", perm_unlink=True)
        partner = self.env["res.partner"].create({"name": "Playground Delete"})
        pg = self._pg(api_key_id=key.id, method="tools/call",
                      tool_name="odoo_unlink",
                      arguments=json.dumps({"model": "res.partner",
                                            "ids": [partner.id]}))
        pg.action_run()
        self.assertEqual(pg.status, "confirm")
        self.assertTrue(partner.exists(), "it must not have deleted anything")

    def test_bad_json_is_a_user_error_not_a_traceback(self):
        from odoo.exceptions import UserError
        pg = self._pg(method="tools/call", tool_name="odoo_search",
                      arguments="{not json")
        with self.assertRaises(UserError):
            pg.action_run()

    def test_the_curl_command_matches_the_call(self):
        pg = self._pg(method="tools/call", tool_name="odoo_search",
                      arguments=json.dumps({"model": "res.partner"}))
        self.assertIn("odoo_search", pg.curl_command)
        self.assertIn("MCP-Protocol-Version: 2026-07-28", pg.curl_command)

    def test_it_writes_an_audit_row(self):
        before = self.env["mn.mcp.audit"].search_count([])
        pg = self._pg(method="tools/list")
        pg.action_run()
        self.assertGreater(self.env["mn.mcp.audit"].search_count([]), before)

    def test_the_picker_mirrors_the_live_catalogue(self):
        Choice = self.env["mn.mcp.tool.choice"]
        Choice.refresh()
        names = set(Choice.search([]).mapped("name"))
        live = {t["name"] for t in self.env["mn.mcp.engine"].tools_list({})["tools"]}
        self.assertEqual(names, live)

    def test_the_picker_drops_tools_that_went_away(self):
        Choice = self.env["mn.mcp.tool.choice"]
        Choice.create({"name": "zz_ghost_tool", "kind": "custom"})
        Choice.refresh()
        self.assertFalse(Choice.search([("name", "=", "zz_ghost_tool")]))


@tagged("post_install", "-at_install")
class TestSelfService(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env["res.users"].create({
            "name": "Portal MCP User", "login": "mcp_portal_user",
            "password": "mcp_portal_user_pw",
        })
        cls.env.ref("mn_mcp_server.group_mcp_user").sudo().write({
            "user_ids": [(4, cls.user.id)]})
        ICP = cls.env["ir.config_parameter"].sudo()
        ICP.set_param("mn_mcp.self_service", "True")
        ICP.set_param("mn_mcp.self_models", "res.partner")
        ICP.set_param("mn_mcp.self_write", "False")
        ICP.set_param("mn_mcp.self_max_keys", "1")

    def test_disabled_by_default_is_refused(self):
        from ..controllers.portal import _self_service_enabled
        self.env["ir.config_parameter"].sudo().set_param("mn_mcp.self_service", "False")
        self.assertFalse(_self_service_enabled(self.env))
        self.env["ir.config_parameter"].sudo().set_param("mn_mcp.self_service", "True")

    def test_the_template_is_the_ceiling(self):
        """A user posting perm_write=1 still gets a read-only key."""
        from ..controllers.portal import _template
        template = _template(self.env)
        self.assertFalse(template["perm_write"])
        self.assertEqual(template["allowed_models"], "res.partner")

    def _csrf(self):
        """Scrape the token out of the page, the way a browser would use it."""
        import re
        page = self.url_open("/my/mcp").text
        match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page)
        self.assertTrue(match, "the page must carry a CSRF token")
        return match.group(1)

    def test_a_user_can_issue_and_reveal_once(self):
        self.authenticate("mcp_portal_user", "mcp_portal_user_pw")
        response = self.url_open("/my/mcp/new", data={
            "name": "Laptop", "csrf_token": self._csrf()})
        self.assertEqual(response.status_code, 200)
        key = self.env["mn.mcp.api_key"].sudo().search(
            [("user_id", "=", self.user.id)], limit=1)
        self.assertTrue(key, "the key should exist")
        self.assertFalse(key.token, "the raw token must be cleared after reveal")
        self.assertFalse(key.perm_write, "the template said read-only")
        self.assertEqual(key.allowed_models, "res.partner")
        self.assertFalse(key.allowed_methods, "self-service keys never get execute")

    def test_posted_permissions_are_ignored(self):
        self.authenticate("mcp_portal_user", "mcp_portal_user_pw")
        self.url_open("/my/mcp/new", data={
            "name": "Sneaky", "perm_write": "1", "perm_unlink": "1",
            "allowed_models": "*",
            "csrf_token": self._csrf()})
        key = self.env["mn.mcp.api_key"].sudo().search(
            [("user_id", "=", self.user.id)], limit=1)
        self.assertFalse(key.perm_write)
        self.assertFalse(key.perm_unlink)
        self.assertEqual(key.allowed_models, "res.partner")

    def test_the_key_limit_holds(self):
        self.authenticate("mcp_portal_user", "mcp_portal_user_pw")
        self.url_open("/my/mcp/new", data={"name": "One", "csrf_token": self._csrf()})
        self.url_open("/my/mcp/new", data={"name": "Two", "csrf_token": self._csrf()})
        self.assertEqual(self.env["mn.mcp.api_key"].sudo().search_count(
            [("user_id", "=", self.user.id), ("state", "=", "active")]), 1)

    def test_you_cannot_revoke_someone_else_s_key(self):
        other = self.env["mn.mcp.api_key"].sudo().create({
            "name": "not-yours", "user_id": self.env.ref("base.user_admin").id})
        self.authenticate("mcp_portal_user", "mcp_portal_user_pw")
        self.url_open("/my/mcp/revoke/%s" % other.id, data={
            "csrf_token": self._csrf()})
        self.assertEqual(other.state, "active", "it must still be active")

    def test_a_user_without_the_group_is_refused(self):
        stranger = self.env["res.users"].create({
            "name": "No MCP", "login": "mcp_no_group", "password": "mcp_no_group_pw"})
        self.assertFalse(stranger.has_group("mn_mcp_server.group_mcp_user"))
