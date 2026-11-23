// The assistant inside Odoo (ADR 0021): a button in the top bar opens a side panel with the
// gateway's web app; the Assistant menus open its inbox and administration. The panel is
// signed in with a one-time ticket made server side; this code never sees any key.

import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const REOPEN = "agent-gateway:reopen";

function consentText() {
    return _t(
        "The assistant will work as you, with exactly your rights in Odoo: it can read what you can read, and it can only propose changes that another person approves. Your questions, and what it reads in Odoo for you, are sent to the AI provider your administrator chose. You can revoke this at any time in your Preferences."
    );
}

/** Ask for consent once; resolves true when the person allows the assistant. */
async function ensureConsent(orm, dialog) {
    const status = await orm.call("res.users", "agent_gateway_status", []);
    if (!status.configured) {
        return { ok: false, status };
    }
    if (status.consent) {
        return { ok: true, status };
    }
    const allowed = await new Promise((resolve) => {
        dialog.add(
            ConfirmationDialog,
            {
                title: _t("Allow the assistant to act on your behalf?"),
                body: consentText(),
                confirmLabel: _t("Allow"),
                cancelLabel: _t("Not now"),
                confirm: () => resolve(true),
                cancel: () => resolve(false),
            },
            { onClose: () => resolve(false) }
        );
    });
    if (!allowed) {
        return { ok: false, status };
    }
    await orm.call("res.users", "agent_gateway_accept", []);
    return { ok: true, status: { ...status, consent: true } };
}

/** The gateway's app in a frame. It asks for a new ticket only when it has no session. */
export class GatewayFrame extends Component {
    static template = "agent_gateway_connector.GatewayFrame";
    static props = { page: String, publicUrl: String, login: String };

    setup() {
        this.orm = useService("orm");
        this.frame = useRef("frame");
        this.origin = new URL(this.props.publicUrl).origin;
        // First without a ticket: an existing session in this browser is reused, no new key.
        // `as` tells the app whom the panel is for, so another person's session is closed.
        const as = encodeURIComponent(this.props.login);
        this.state = useState({ src: `${this.props.publicUrl}/app/embed/${this.props.page}?as=${as}`, error: null });
        this.onMessage = (event) => this.handleMessage(event);
        onMounted(() => window.addEventListener("message", this.onMessage));
        onWillUnmount(() => window.removeEventListener("message", this.onMessage));
    }

    async handleMessage(event) {
        if (event.origin !== this.origin || event.source !== this.frame.el?.contentWindow) {
            return;
        }
        if (event.data?.type !== REOPEN || this.opening) {
            return;
        }
        this.opening = true;
        try {
            const { url } = await this.orm.call("res.users", "agent_gateway_ticket", [this.props.page]);
            this.state.error = null;
            this.state.src = url;
        } catch (error) {
            this.state.error = error.data?.message || _t("The assistant could not be reached.");
        } finally {
            this.opening = false;
        }
    }
}

export class AssistantSystray extends Component {
    static template = "agent_gateway_connector.Systray";
    static components = { GatewayFrame };
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({ open: false, publicUrl: null, login: null });
    }

    async toggle() {
        if (this.state.open) {
            this.state.open = false;
            return;
        }
        const { ok, status } = await ensureConsent(this.orm, this.dialog);
        if (!status.configured) {
            this.notification.add(
                _t("The assistant is not configured yet: ask an administrator (Settings → AI assistant)."),
                { type: "warning" }
            );
        }
        if (ok) {
            this.state.publicUrl = status.public_url;
            this.state.login = status.login;
            this.state.open = true;
        }
    }

    close() {
        this.state.open = false;
    }
}

/** Assistant menus: the chat, the approvals inbox or the administration, full page. */
export class EmbedAction extends Component {
    static template = "agent_gateway_connector.EmbedAction";
    static components = { GatewayFrame };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.page = this.props.action?.params?.page || "chat";
        this.state = useState({ ready: false, publicUrl: null, login: null, message: null });
        onMounted(() => this.start());
    }

    async start() {
        const { ok, status } = await ensureConsent(this.orm, this.dialog);
        if (!status.configured) {
            this.state.message = _t(
                "The assistant is not configured yet: ask an administrator (Settings → AI assistant)."
            );
        } else if (!ok) {
            this.state.message = _t("The assistant works only after you allow it.");
        } else {
            this.state.publicUrl = status.public_url;
            this.state.login = status.login;
            this.state.ready = true;
        }
    }
}

registry.category("systray").add("agent_gateway_connector.assistant", { Component: AssistantSystray }, { sequence: 1 });
registry.category("actions").add("agent_gateway_embed", EmbedAction);
