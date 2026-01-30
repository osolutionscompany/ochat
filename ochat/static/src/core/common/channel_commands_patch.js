/* @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

const commandRegistry = registry.category("discuss.channel_commands");

// Add /status command for O'Chat channels
commandRegistry.add("status", {
    channel_types: ["ochat"],
    help: _t("Show connection status and encryption info"),
    methodName: "execute_command_status",
});

// Extend /who command to support O'Chat channels
const whoCommand = commandRegistry.get("who");
if (whoCommand) {
    commandRegistry.add("who", {
        ...whoCommand,
        channel_types: [...(whoCommand.channel_types || []), "ochat"],
    }, { force: true });
}
