"""Demo data for the Odoo Agent Gateway. Runs INSIDE Odoo (`odoo shell`), never in the gateway.

Creates two users with different sales permissions, a few sale orders for each, and an
API key per user. Safe to run more than once: users, partners and orders are reused;
a fresh API key is issued on every run. The result is printed as one JSON line that
`setup_demo.py` reads. `env` is provided by `odoo shell`.
"""

import datetime
import json
import secrets

env = env  # noqa: F821  (provided by odoo shell)

group_user = env.ref("base.group_user")
group_own_docs = env.ref("sales_team.group_sale_salesman")  # Sales: own documents only
group_sales_admin = env.ref("sales_team.group_sale_manager")  # Sales: administrator

Users = env["res.users"].with_context(no_reset_password=True)


def ensure_user(login, name, groups):
    user = Users.search([("login", "=", login)], limit=1)
    values = {"groups_id": [(6, 0, [group_user.id] + [g.id for g in groups])]}
    if user:
        user.write(values)
    else:
        user = Users.create(
            {"name": name, "login": login, "email": f"{login}@example.com", **values}
        )
    return user


ana = ensure_user("ana", "Ana (Sales)", [group_own_docs])
luis = ensure_user("luis", "Luis (Management)", [group_sales_admin])


def ensure_partner(name):
    partner = env["res.partner"].search([("name", "=", name)], limit=1)
    return partner or env["res.partner"].create({"name": name, "is_company": True})


customers = [ensure_partner("Acme Demo SL"), ensure_partner("Globex Demo SA")]
product = env["product.product"].search([("sale_ok", "=", True)], limit=1)
if not product:
    raise SystemExit("No saleable product found: was the database created with demo data?")


def ensure_order(ref, user, customer, quantity):
    order = env["sale.order"].search([("client_order_ref", "=", ref)], limit=1)
    if not order:
        order = env["sale.order"].create(
            {
                "partner_id": customer.id,
                "user_id": user.id,
                "client_order_ref": ref,
                "order_line": [(0, 0, {"product_id": product.id, "product_uom_qty": quantity})],
            }
        )
    return order


orders = {
    "ana": [
        ensure_order("DEMO-ANA-1", ana, customers[0], 2).id,
        ensure_order("DEMO-ANA-2", ana, customers[1], 5).id,
    ],
    "luis": [
        ensure_order("DEMO-LUIS-1", luis, customers[0], 10).id,
        ensure_order("DEMO-LUIS-2", luis, customers[1], 1).id,
    ],
}

# Replace Odoo's default administrator password with a random one. It is handed back to
# setup_demo.py, which stores it in the git-ignored .env.demo-keys so the owner keeps access.
admin_password = secrets.token_urlsafe(24)
env.ref("base.user_admin").password = admin_password

expires = datetime.datetime.now() + datetime.timedelta(days=90)
keys = {
    user.login: env["res.users.apikeys"]
    .with_user(user)
    .sudo()
    ._generate(None, "odoo-agent-gateway demo", expires)
    for user in (ana, luis)
}

env.cr.commit()
print(
    "DEMO_RESULT_JSON="
    + json.dumps({"keys": keys, "orders": orders, "admin_password": admin_password})
)
