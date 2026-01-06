/** @odoo-module **/

import { Message } from "@mail/core/common/message_model";
import { patch } from "@web/core/utils/patch";

/**
 * Patch du modèle Message pour ajouter les champs de statut O'Chat
 */
patch(Message.prototype, {
    ochat_fastapi_message_id: undefined,
    ochat_delivery_status: undefined,
    ochat_retry_count: undefined,
    ochat_failed_reason: undefined,
    ochat_delivered_at: undefined,
    ochat_read_at: undefined,
});
