from . import models
from . import controllers


def post_init_hook(env):
    """Mint the confirmation-signing secret before anything can ask for it.

    ``confirm._secret()`` generates one lazily on first use. On a brand-new
    database that first use is inside a live request, and an Odoo 19 read-only
    request that writes is REPLAYED — so the state handed to the client can be
    signed with a secret that the replay then overwrites. The client comes back
    with a confirmation the server no longer recognises, and a delete the user
    approved silently asks again.

    Observed once in the test suite. Creating it at install removes the window
    entirely, which is cheaper than making the lazy path race-free.
    """
    import secrets
    params = env["ir.config_parameter"].sudo()
    if not params.get_param("mn_mcp.confirm_secret"):
        params.set_param("mn_mcp.confirm_secret", secrets.token_urlsafe(48))
