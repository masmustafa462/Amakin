# -*- coding: utf-8 -*-
{
    "name": "Odoo MCP Server | Free | Claude · ChatGPT · Gemini · AI Agents",
    "version": "19.0.4.0.0",
    "category": "Tools",
    "summary": "Turn Odoo into an MCP tool server. Free LGPL-3. Speaks the current "
               "2026-07-28 stateless MCP spec AND every earlier revision, negotiated "
               "per request. Connect Claude, ChatGPT, Cursor and any MCP client to "
               "live Odoo data — 24 tools, scoped API keys, model whitelists, "
               "permission enforcement and a full audit log.",
    "description": """
Odoo MCP Server (FREE)
======================
Expose Odoo as a Model Context Protocol (MCP) tool server so AI assistants
can read and write your live ERP data — safely.

Protocol support — current, and backwards compatible
----------------------------------------------------
MCP has been revised four times, and the **2026-07-28** revision is a breaking
redesign: it removes the ``initialize`` handshake and protocol-level sessions,
makes every request self-contained, and adds required result fields.

This server negotiates the revision **per request** and speaks all of them:

* ``2026-07-28`` — stateless core, ``server/discover``, ``resultType``,
  cacheable list results (``ttlMs`` / ``cacheScope``), renumbered error codes,
  ``Mcp-Method`` routing-header validation
* ``2025-11-25`` · ``2025-06-18`` · ``2025-03-26`` · ``2024-11-05``

A 2024-era client keeps working untouched after you upgrade — it never sees
the new fields. A 2026 client gets the new shape without an initialize call.
Tools are returned in a deterministic order so clients can cache the list and
the model's prompt cache stays warm.

Custom tools — teach it your business, without code
---------------------------------------------------
The built-in tools are primitives, so the model has to work out what "overdue"
or "at risk" means in *your* Odoo. It usually gets there. Usually is not good
enough on a Monday morning.

Define a tool in the Odoo UI instead:

    name         overdue_invoices
    description  Invoices past their due date and not yet paid.
    model        account.move
    domain       [("move_type","=","out_invoice"),
                  ("payment_state","!=","paid"),
                  ("invoice_date_due","<",{as_of})]
    parameter    as_of · date · defaults to today

Now the AI calls one tool with one obvious argument, and *the business* decides
what overdue means rather than the model improvising it.

* Three kinds — find records, aggregate/count by, or run a server action
* Typed parameters substituted into the domain as literals, so a parameter can
  never inject its own clause
* Broken domains are caught when you save, not at 3am inside an answer
* Custom tools run as the API key's user, inside that key's allowed models.
  They can narrow what the AI sees; they can never widen it
* No free-form Python: a tool that runs arbitrary code is a remote shell with
  extra steps. Point one at an ``ir.actions.server`` if you genuinely need it —
  that is Odoo's own reviewed mechanism, with its own permissions

Confirm before it deletes — the guard rail nobody else ships
------------------------------------------------------------
Odoo's access rules stop an AI doing what the *user* may not do. They do not
stop it doing something the user could do but did not mean to. This does.

Deleting records, editing in bulk, or calling a model method now stops until a
human has seen **exactly what is about to happen** and agreed:

    Permanently delete 42 record(s) from Customer Invoice (account.move).
    This cannot be undone.                              [ Confirm ]  [ Cancel ]

* Built on **MRTR** (Multi Round-Trip Requests, 2026-07-28) — stateless, so it
  works behind a load balancer with no sticky sessions
* The approval is **cryptographically bound to the exact call**: a confirmation
  for "delete 3 draft quotes" cannot be replayed to authorise "delete 3000
  invoices". Forged or expired state is refused.
* Clients without elicitation are told to re-call with ``confirm: true`` — the
  same protection on every protocol revision
* Thresholds are yours: always confirm deletes, confirm updates over N records,
  confirm arbitrary method calls. Or switch the whole thing off.

OAuth 2.1 — connect a whole team without pasting tokens
--------------------------------------------------------
Pasting a bearer token into a connector URL puts it in browser history, proxy
logs and screenshots. With OAuth, a user clicks Connect, logs in to Odoo, sees
a consent screen, and every call afterwards runs **as them**.

Implemented as both authorization server and resource server, so there is no
second system to install:

* **Protected Resource Metadata** (RFC 9728) and **Authorization Server
  Metadata** (RFC 8414) — discovery is automatic; the 401 tells the client
  where to go
* **PKCE with S256 only** — plain is not offered
* **Client ID Metadata Documents** — the modern registration path; a client
  publishes its own metadata and needs no pre-registration. Dynamic Client
  Registration is still accepted for clients that only speak it
* **Audience-bound tokens** (RFC 8707) — a token minted for another MCP server
  is refused here, which is the confused-deputy attack the spec names
* **Refresh-token rotation**, and a replayed authorization code revokes every
  token it issued
* **Scopes** ``odoo:read`` / ``odoo:write`` / ``odoo:admin``, mapped onto the
  same permission model as an API key — one place decides what a caller may do
* Access tokens are refused in the query string, per the spec

The semantic layer — stop it guessing what your words mean
----------------------------------------------------------
A model pointed at a raw Odoo database is doing archaeology. It sees
``account.move`` with 180 fields and has to infer that "outstanding" is
``amount_residual``, that a customer invoice is ``move_type = out_invoice``,
and that "churned" is a state your company invented. It usually gets there.
When it does not, it does not say so — it answers confidently, with the
wrong number.

Three things fix that, and none of them need code:

* **Business glossary** — your definition of "churn", "MRR", "live job",
  optionally pinned to the model, field and domain that expresses it
* **Business metrics** — a named, reviewed calculation. The AI asks for
  ``metric_mrr`` and gets the number your CFO would have produced, not one it
  improvised from a group-by. Time windows, breakdowns and units included
* **Model hints** — "for revenue use account.move, not sale.order; sale.order
  includes quotations that never became money". This is the highest-value
  sentence you can write down, because it stops the wrong query being made

Every one of these narrows. None of them grants access: a metric runs as the
API key's user, inside that key's model whitelist.

Playground — test the connection here, not in someone else's chat window
-------------------------------------------------------------------------
Every connector fails the same way: you configure it, hand the URL to a
colleague, and find out three days later that a permission was missing.

The playground runs the call in Odoo, through the same dispatch the wire uses.
Pick a key, pick a tool, run it — you see the JSON, the latency, and the audit
row it produced, plus the equivalent ``curl`` command to replay outside Odoo.

It runs as the **key's** user, not as you, and it does **not** bypass the guard
rails. Ask it to delete and you get the same confirmation prompt a client
would. A test button that is more permissive than production tests the wrong
thing.

Self-service keys — connect a team without becoming a key vending machine
--------------------------------------------------------------------------
Issuing keys by hand stops working at about six colleagues. What happens next
is predictable: somebody makes one shared key with every permission, which is
exactly what scoping exists to prevent.

Switch on self-service and each user issues their own at ``/my/mcp``. They
choose a label. Everything else — which models, which permissions, what quota,
how many keys — comes from a template you set once. A user cannot widen their
own key, and their key still runs under their own record rules.

Structured output and streaming
--------------------------------
* **outputSchema + structuredContent** — tools declare the shape they return,
  so a client stops parsing prose out of a text block and starts chaining calls
* **Streamable HTTP** — a client that sends ``Accept: text/event-stream`` gets
  an SSE-framed response instead of a second, plainer request
* **Resource templates** — ``odoo://record/{model}/{id}``,
  ``odoo://search/{model}?domain=…``, ``odoo://metric/{name}``,
  ``odoo://report/{name}/{id}``, ``odoo://attachment/{id}``
* **Cursor pagination** on every list method, with opaque cursors

Endpoints (JSON-RPC 2.0 over HTTP)
----------------------------------
* ``/mcp`` — server/discover + tools/list + tools/call + resources/list +
  resources/read + prompts/list + prompts/get (+ initialize for old clients)
* Bearer-token authentication using scoped API keys
* Every tool carries ``readOnlyHint`` / ``destructiveHint`` annotations, so a
  client knows which calls are safe to run unattended and which need a human

Out-of-the-box tools
--------------------
* ``odoo_search`` / ``odoo_search_read`` / ``odoo_search_count`` — find records
* ``odoo_read`` / ``odoo_read_group`` / ``odoo_name_search`` — read and aggregate
* ``odoo_create`` / ``odoo_create_many`` / ``odoo_copy`` / ``odoo_find_or_create``
* ``odoo_write`` — update; ``odoo_unlink`` — delete (confirmed first)
* ``odoo_fields_get`` / ``odoo_get_view`` / ``odoo_list_models`` — discover schema
* ``odoo_describe_model`` / ``odoo_glossary`` / ``odoo_list_metrics`` — the semantic layer
* ``odoo_message_post`` / ``odoo_activity_schedule`` / ``odoo_send_email``
* ``odoo_print_report`` / ``odoo_attach_file`` — documents in and out
* ``odoo_run_server_action`` / ``odoo_execute`` — whitelist-gated
* ``odoo_menu_tree`` / ``odoo_user_context`` — orientation

Tool names use underscores, not dots: MCP clients reject a dot in a tool name.

Safety rails
------------
* **Scoped API keys** — per-key allowed models, permissions (r/w/c/d),
  per-day request quota, expiry date
* **Permission enforcement** — every call runs under the API key's user;
  Odoo's standard ACL + record rules apply
* **Audit log** — every request stored with method, args (hashed), latency,
  success / failure, response code
* **Rate limiting** — daily quota per key

Pricing
-------
**FREE** under LGPL-3. Source code on GitHub. Lifetime updates.
The premium paid alternatives are $200+. This one is free because every
MENA Odoo shop should have AI access without paying twice.
    """,
    "author": "Moaz Nabil",
    "website": "https://github.com/moaaznaabilali",
    "support": "moaaznaabilali@gmail.com",
    "license": "LGPL-3",
    "depends": ["base", "mail", "web"],
    "data": [
        "security/mcp_security.xml",
        "security/ir.model.access.csv",
        "data/sequences.xml",
        "data/config_data.xml",
        "data/cron.xml",
        "data/prompts_data.xml",
        "views/mcp_api_key_views.xml",
        "views/oauth_templates.xml",
        "views/mcp_oauth_views.xml",
        "views/mcp_tool_views.xml",
        "views/mcp_semantic_views.xml",
        "views/mcp_playground_views.xml",
        "views/portal_templates.xml",
        "views/mcp_audit_views.xml",
        "views/mcp_prompt_views.xml",
        "views/res_config_settings_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "mn_mcp_server/static/src/lib/chart.umd.min.js",
            "mn_mcp_server/static/src/dashboard/mcp_dashboard.js",
            "mn_mcp_server/static/src/dashboard/mcp_dashboard.xml",
        ],
    },
    "images": ["static/description/banner.png"],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": True,
    "auto_install": False,
}
