/** @odoo-module **/

import { Message } from "@mail/core/common/message_model";
import { patch } from "@web/core/utils/patch";

/**
 * Patch of the Message model to add O'Chat status fields
 */
patch(Message.prototype, {
    ochat_fastapi_message_id: undefined,
    ochat_delivery_status: undefined,
    ochat_retry_count: undefined,
    ochat_failed_reason: undefined,
    ochat_delivered_at: undefined,
    ochat_read_at: undefined,
});
