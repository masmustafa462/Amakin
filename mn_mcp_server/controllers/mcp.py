# -*- coding: utf-8 -*-
"""MCP transport.

Authenticate, negotiate a protocol revision, frame a response. Everything the
protocol actually *does* lives in ``mn.mcp.engine`` — see the note at the top
of that file for why.
"""
import json
import logging
import time

from odoo import http, fields
from odoo.http import request

from . import confirm as C
from . import protocol as P
from ..models.mcp_engine import McpForbidden

_logger = logging.getLogger(__name__)

JSONRPC = "2.0"
# Kept for the module version string reported to clients.
SERVER_VERSION = "19.0.4.0.0"


def _err(code, message, rpc_id=None, data=None):
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": JSONRPC, "id": rpc_id, "error": error}


def _ok(result, rpc_id=None):
    return {"jsonrpc": JSONRPC, "id": rpc_id, "result": result}


class McpController(http.Controller):

    @http.route("/mcp", type="http", auth="public", methods=["POST", "OPTIONS"],
                csrf=False, cors="*", save_session=False)
    def mcp(self, **kw):  # noqa: C901 — one request, one linear path
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=[
                ("Access-Control-Allow-Origin", "*"),
                ("Access-Control-Allow-Methods", "POST, OPTIONS"),
                ("Access-Control-Allow-Headers",
                 "Authorization, Content-Type, MCP-Protocol-Version, Mcp-Method, Mcp-Name"),
            ])

        env = request.env(su=True)
        enabled = env["ir.config_parameter"].get_param(
            "mn_mcp.enabled", "True") in ("True", "true", "1", True)
        if not enabled:
            return self._respond(_err(P.ERR_DISABLED, "MCP endpoint disabled"), status=503)

        # Read the raw JSON body. Some clients POST JSON without the
        # 'application/json' content-type; Werkzeug then parses the body into
        # form keys and request.httprequest.data is empty — recover it from kw
        # (ignoring the optional ?key= auth param).
        raw = request.httprequest.data
        if not raw and kw:
            raw = (next((k for k in kw if k != "key"), "") or "").encode()
        try:
            body = json.loads(raw or b"{}")
        except Exception:  # noqa: BLE001
            return self._respond(_err(P.ERR_PARSE, "Parse error"))

        rpc_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}
        ip = request.httprequest.remote_addr

        # The revision is settled per request: from 2026-07-28 there is no
        # handshake to settle it once, so it travels in _meta or the header.
        revision, unsupported = P.negotiate(body, request.httprequest.headers)
        if unsupported:
            return self._respond(_err(
                P.err_code(P.ERR_UNSUPPORTED_VERSION, P.LATEST_REVISION),
                "Unsupported protocol version",
                rpc_id, data={"supported": list(P.SUPPORTED_REVISIONS)}), status=400)

        # 2026-07-28 requires Mcp-Method / Mcp-Name on every POST so proxies
        # can route without parsing the body. We validate rather than demand:
        # rejecting a request whose headers are merely absent would break
        # clients that are otherwise compliant, but a header that CONTRADICTS
        # the body is a routing bug worth surfacing.
        header_method = request.httprequest.headers.get("Mcp-Method")
        if header_method and method and header_method != method:
            return self._respond(_err(
                P.err_code(P.ERR_HEADER_MISMATCH, revision),
                "Mcp-Method header '%s' does not match body method '%s'"
                % (header_method, method), rpc_id), status=400)

        # JSON-RPC notifications carry no "id" and MUST NOT receive a response.
        # MCP clients send 'notifications/initialized' right after initialize and
        # before tools/list; replying with an error aborts the handshake.
        if "id" not in body or (method or "").startswith("notifications/"):
            return request.make_response("", status=202, headers=[
                ("Access-Control-Allow-Origin", "*"),
            ])

        # Auth token: prefer the Authorization header (mcp-remote, SDK clients),
        # but also accept it in the URL (?key=…) so MCP clients that only take a
        # URL — like Claude's native "custom connector" — can authenticate too.
        token = (request.httprequest.headers.get("Authorization") or "").replace("Bearer ", "").strip()
        from_url = False
        if not token:
            # Only a *static API key* may travel in the URL, and only because
            # Claude's custom-connector dialog has no header field. OAuth
            # access tokens must never be accepted here — the spec forbids
            # tokens in the query string, and a URL leaks into history, proxy
            # logs and screenshots.
            token = (request.httprequest.args.get("key") or "").strip()
            from_url = bool(token)

        api_key = env["mn.mcp.api_key"].authenticate(token)
        if not api_key and token and not from_url:
            # Not a static key — try it as an OAuth access token, bound to
            # this server as its audience (RFC 8707).
            api_key = env["mn.mcp.oauth.token"].authenticate(
                token, audience=self._canonical_resource())

        # server/discover is unauthenticated: a client must be able to learn
        # which revisions we speak before it has credentials, and the answer
        # leaks nothing about the database.
        if method == "server/discover":
            return self._respond(_ok(P.discover(SERVER_VERSION), rpc_id))

        # initialize is open. Removed in 2026-07-28, kept here because the
        # installed base of older clients still opens with it.
        if method == "initialize":
            # echo the client's requested protocol version when supplied, so
            # newer clients (2025-xx-xx) negotiate cleanly; fall back otherwise.
            return self._respond(_ok({
                "protocolVersion": revision,
                "serverInfo": P.server_info(SERVER_VERSION),
                "capabilities": P.capabilities(revision),
            }, rpc_id))

        if not api_key:
            env["mn.mcp.webhook"].fire({"event": "auth_fail", "status": "auth_fail",
                                        "ip": ip, "method": method})
            return self._respond(
                _err(P.ERR_AUTH, "Authentication failed", rpc_id),
                status=401, extra_headers=[("WWW-Authenticate", self._challenge())])

        # IP allowlist
        if not api_key.is_ip_allowed(ip):
            env["mn.mcp.audit"].log(
                api_key_id=api_key.id, method=method, status="forbidden",
                error_msg="IP %s not in allowlist" % ip, ip=ip, args=params,
            )
            return self._respond(_err(P.ERR_IP, "IP %s not allowed" % ip, rpc_id), status=403)

        # Rate limit
        if not api_key.check_rate_limit():
            env["mn.mcp.audit"].log(
                api_key_id=api_key.id, method=method, status="over_quota",
                error_msg="Rate limit (%s/min) exceeded" % api_key.rate_per_minute,
                ip=ip, args=params,
            )
            env["mn.mcp.webhook"].fire({"event": "rate_limit", "status": "over_quota",
                                        "key": api_key.name, "ip": ip})
            return self._respond(
                _err(P.ERR_RATE_LIMIT, "Rate limit exceeded — try again in 60s", rpc_id),
                status=429, extra_headers=[("Retry-After", "60")])

        start = time.time()
        engine = env["mn.mcp.engine"]
        try:
            user_env = request.env(user=api_key.user_id.id, su=False)

            if method == "tools/list":
                result = engine.tools_list(params)
            elif method == "tools/call":
                result = engine.tools_call(api_key, user_env, params)
            elif method == "resources/list":
                result = engine.resources_list(api_key, params)
            elif method == "resources/templates/list":
                result = engine.resource_templates(params)
            elif method == "resources/read":
                result = engine.resources_read(api_key, user_env, params)
            elif method == "prompts/list":
                result = engine.prompts_list(params)
            elif method == "prompts/get":
                result = engine.prompts_get(params)
            elif method == "ping" and not P.is_at_least(revision, P.STATELESS_FROM):
                # Removed in 2026-07-28; still answered for older clients.
                result = {}
            elif method == "logging/setLevel" and not P.is_at_least(revision, P.STATELESS_FROM):
                result = {}
            else:
                return self._respond(_err(P.ERR_METHOD_NOT_FOUND,
                                          "Method '%s' not found" % method, rpc_id))

            latency = int((time.time() - start) * 1000)
            api_key.sudo().write({
                "last_used": fields.Datetime.now(),
                "last_ip": ip,
                "total_calls": api_key.total_calls + 1,
            })
            env["mn.mcp.audit"].log(
                api_key_id=api_key.id, method=method,
                status="ok", latency_ms=latency,
                args=params, ip=ip,
                tool_name=params.get("name"),
                model_target=(params.get("arguments") or {}).get("model"),
            )
            result = P.decorate_result(result, revision, method, SERVER_VERSION)
            return self._respond(_ok(result, rpc_id))
        except McpForbidden as e:
            env["mn.mcp.audit"].log(
                api_key_id=api_key.id, method=method, status="forbidden",
                error_msg=str(e), ip=ip, args=params,
                tool_name=params.get("name"),
                model_target=(params.get("arguments") or {}).get("model"),
            )
            env["mn.mcp.webhook"].fire({"event": "forbidden", "status": "forbidden",
                                        "key": api_key.name, "ip": ip, "msg": str(e)})
            return self._respond(_err(P.ERR_FORBIDDEN, str(e), rpc_id))
        except Exception as e:  # noqa: BLE001
            _logger.exception("MCP error")
            env["mn.mcp.audit"].log(
                api_key_id=api_key.id, method=method, status="error",
                error_msg=str(e)[:255], ip=ip, args=params,
            )
            return self._respond(_err(P.ERR_INTERNAL, "Internal error: %s" % e, rpc_id))

    # ───────────── helpers ───────────────────────────────────────────
    def _canonical_resource(self):
        """The RFC 8707 identifier a token must be bound to: our /mcp URL."""
        from .oauth import base_url, MCP_PATH
        return "%s%s" % (base_url(), MCP_PATH)

    def _challenge(self):
        """RFC 6750 challenge naming our metadata document.

        This is the whole point of the discovery chain: a client that gets a
        401 learns from this header where to find the authorization server,
        with no configuration from the user.
        """
        from .oauth import base_url
        from ..models.mcp_oauth import SCOPES_SUPPORTED
        meta = "%s/.well-known/oauth-protected-resource" % base_url()
        return ('Bearer resource_metadata="%s", scope="%s"'
                % (meta, " ".join(SCOPES_SUPPORTED[:1])))

    def _wants_sse(self):
        """Streamable HTTP: the client offers SSE, so we may frame in SSE.

        This is a framing choice, not a different protocol — the body is the
        same single JSON-RPC response. Clients built on the official SDK's
        StreamableHTTPClientTransport send this Accept header and handle either
        answer; sending SSE when they asked for it avoids the transport falling
        back to a second, plainer request.
        """
        accept = (request.httprequest.headers.get("Accept") or "")
        return "text/event-stream" in accept

    def _respond(self, body, status=200, extra_headers=None):
        payload = json.dumps(body)
        if self._wants_sse() and status == 200:
            # One event, then the stream ends. A long-lived stream would need
            # a session to correlate with, and 2026-07-28 deliberately has no
            # sessions — so there is nothing here worth keeping open.
            headers = [("Content-Type", "text/event-stream"),
                       ("Cache-Control", "no-cache, no-transform"),
                       ("Connection", "keep-alive"),
                       ("X-Accel-Buffering", "no"),
                       ("Access-Control-Allow-Origin", "*")]
            if extra_headers:
                headers.extend(extra_headers)
            return request.make_response(
                "event: message\ndata: %s\n\n" % payload, status=status, headers=headers)

        headers = [("Content-Type", "application/json"),
                   ("Access-Control-Allow-Origin", "*")]
        if extra_headers:
            headers.extend(extra_headers)
        return request.make_response(payload, status=status, headers=headers)
