/* @odoo-module */

import { ThreadService } from "@mail/core/common/thread_service";
import { patch } from "@web/core/utils/patch";

patch(ThreadService.prototype, {
    /**
     * Override executeCommand to handle action results (like opening wizards)
     * @override
     */
    async executeCommand(thread, command, body = "") {
        const result = await super.executeCommand(...arguments);

        // If the command returns an action (like /ticket), execute it
        if (result && result.type === 'ir.actions.act_window') {
            this.env.services.action.doAction(result);
        }

        return result;
    },
});
