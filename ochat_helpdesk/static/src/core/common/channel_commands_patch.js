/* @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

const commandRegistry = registry.category("discuss.channel_commands");

// Add /ticket command for O'Chat channels (requires helpdesk)
commandRegistry.add("ticket", {
    channel_types: ["ochat"],
    help: _t("Create a helpdesk ticket from this conversation"),
    methodName: "execute_command_ticket",
});
