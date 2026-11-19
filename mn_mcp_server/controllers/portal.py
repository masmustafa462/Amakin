# -*- coding: utf-8 -*-
"""Self-service keys at /my/mcp.

The bottleneck in every rollout is the same: one administrator, one key per
colleague, issued by hand over chat. It does not scale past about six people,
and it fails in a specific way — the administrator gets tired of it and issues
one shared key with every permission, which is exactly what the scoping in this
module exists to prevent.

So a user can issue their own. What they cannot do is decide what it may reach:
the models, the permissions and the quota all come from a template the
administrator sets in Settings. A user's key can only ever be a narrower view
of what that user could already see in Odoo, under their own record rules.

Turned off by default. An administrator switches it on, sets the template, and
grants the MCP User group to whoever should have it.
"""
import logging

from odoo import _, http
from odoo.exceptions import AccessError
from odoo.http import request

_logger = logging.getLogger(__name__)


def _self_service_enabled(env):
    return env["ir.config_parameter"].sudo().get_param(
        "mn_mcp.self_service", "False") in ("True", "true", "1", True)


def _template(env):
    """The ceiling an end user's key is issued against."""
    ICP = env["ir.config_parameter"].sudo()
    return {
        "allowed_models": ICP.get_param("mn_mcp.self_models", "") or "",
        "perm_read": ICP.get_param("mn_mcp.self_read", "True") in ("True", "true", "1"),
        "perm_write": ICP.get_param("mn_mcp.self_write", "False") in ("True", "true", "1"),
        "perm_create": ICP.get_param("mn_mcp.self_create", "False") in ("True", "true", "1"),
        "perm_unlink": ICP.get_param("mn_mcp.self_unlink", "False") in ("True", "true", "1"),
        "daily_quota": int(ICP.get_param("mn_mcp.self_quota", "500") or 500),
        "rate_per_minute": int(ICP.get_param("mn_mcp.self_rate", "30") or 30),
        "max_keys": int(ICP.get_param("mn_mcp.self_max_keys", "3") or 3),
    }


class McpPortal(http.Controller):

    def _guard(self):
        user = request.env.user
        if user._is_public():
            raise AccessError(_("Please sign in."))
        if not _self_service_enabled(request.env):
            raise AccessError(_("Self-service MCP keys are not enabled here. "
                                "Ask your Odoo administrator for a key."))
        if not user.has_group("mn_mcp_server.group_mcp_user"):
            raise AccessError(_("You are not allowed to issue MCP keys."))
        return user

    def _render(self, values=None):
        user = request.env.user
        Key = request.env["mn.mcp.api_key"].sudo()
        keys = Key.search([("user_id", "=", user.id)], order="create_date desc")
        template = _template(request.env)
        vals = {
            "keys": keys,
            "template": template,
            "at_limit": len(keys.filtered(lambda k: k.state == "active")) >= template["max_keys"],
            "page_name": "mcp_keys",
        }
        vals.update(values or {})
        return request.render("mn_mcp_server.portal_mcp_keys", vals)

    @http.route(["/my/mcp"], type="http", auth="user")
    def portal_mcp(self, **kw):
        self._guard()
        return self._render()

    @http.route(["/my/mcp/new"], type="http", auth="user",
                methods=["POST"], csrf=True)
    def portal_mcp_new(self, **post):
        user = self._guard()
        Key = request.env["mn.mcp.api_key"].sudo()
        template = _template(request.env)

        active = Key.search_count([("user_id", "=", user.id), ("state", "=", "active")])
        if active >= template["max_keys"]:
            return self._render({"error": _(
                "You already have %s active keys, which is the limit. "
                "Revoke one first.", template["max_keys"])})

        label = (post.get("name") or "").strip() or _("My AI assistant")
        # Everything except the label comes from the template. A user cannot
        # widen their own key, by post parameter or otherwise.
        key = Key.create({
            "name": "%s · %s" % (label[:60], user.name),
            "user_id": user.id,
            "allowed_models": template["allowed_models"],
            "perm_read": template["perm_read"],
            "perm_write": template["perm_write"],
            "perm_create": template["perm_create"],
            "perm_unlink": template["perm_unlink"],
            "daily_quota": template["daily_quota"],
            "rate_per_minute": template["rate_per_minute"],
            # A self-service key never gets odoo_execute: the whitelist is
            # empty and only an administrator can fill it in.
            "allowed_methods": "",
        })
        token = key.token
        # The connector URL has to be built while the token is still in hand —
        # after the reveal the record no longer knows it, which is the point.
        connect_url = key.connect_url
        # Same one-time reveal as the backend: shown now, then cleared.
        key.write({"token": False})
        _logger.info("MCP self-service key %s issued to %s", key.id, user.login)
        return self._render({
            "new_token": token,
            "new_key": key,
            "new_connect_url": "%s?key=%s" % (connect_url, token),
        })

    @http.route(["/my/mcp/revoke/<int:key_id>"], type="http", auth="user",
                methods=["POST"], csrf=True)
    def portal_mcp_revoke(self, key_id, **post):
        user = self._guard()
        key = request.env["mn.mcp.api_key"].sudo().browse(key_id)
        # Browsing by id from a URL: check ownership before acting, or one
        # user revokes another's key by changing a number.
        if not key.exists() or key.user_id.id != user.id:
            return self._render({"error": _("That key is not yours.")})
        key.action_revoke()
        return self._render({"info": _("Key revoked. Any client using it will "
                                       "stop working immediately.")})
