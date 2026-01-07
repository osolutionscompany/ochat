/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { Thread } from "@mail/core/common/thread_model";
import { patch } from "@web/core/utils/patch";

const commandRegistry = registry.category("discuss.channel_commands");

// Add /status command for O'Chat channels
commandRegistry.add("status", {
    channel_types: ["ochat"],
    help: _t("Show connection status and encryption info"),
    methodName: "execute_command_status",
});

// Add /ticket command for O'Chat channels
commandRegistry.add("ticket", {
    channel_types: ["ochat"],
    help: _t("Create a helpdesk ticket from this conversation"),
    methodName: "execute_command_ticket",
});

// Extend /who command to support O'Chat channels
const whoCommand = commandRegistry.get("who");
if (whoCommand) {
    commandRegistry.add("who", {
        ...whoCommand,
        channel_types: [...(whoCommand.channel_types || []), "ochat"],
    }, { force: true });
}

// Patch executeCommand to handle action results
patch(Thread.prototype, {
    async executeCommand(command, body = "") {
        const result = await super.executeCommand(command, body);

        // If the command returns an action (like /ticket), execute it
        if (result && result.type === 'ir.actions.act_window') {
            this.store.env.services.action.doAction(result);
        }

        return result;
    },
});
