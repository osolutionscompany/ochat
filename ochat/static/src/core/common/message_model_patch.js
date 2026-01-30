/** @odoo-module **/

import { Message } from "@mail/core/common/message_model";
import { fields } from "@mail/core/common/record";
import { patch } from "@web/core/utils/patch";

/**
 * Patch du modèle Message pour ajouter les champs de statut O'Chat
 * V19: Declare fields in setup() method when patching
 */
patch(Message.prototype, {
    ochat_fastapi_message_id: undefined,
    ochat_delivery_status: undefined,
    ochat_retry_count: undefined,
    ochat_failed_reason: undefined,
    ochat_delivered_at: undefined,
    ochat_read_at: undefined,

    /**
     * Disable message editing for O'Chat channels
     * @override
     */
    get editable() {
        if (this.thread?.channel_type === "ochat") {
            return false;
        }
        return super.editable;
    },

    /**
     * Disable reply for O'Chat channels
     * @override
     */
    canReplyTo(thread) {
        if (thread?.channel_type === "ochat") {
            return false;
        }
        return super.canReplyTo(thread);
    },

    /**
     * Disable reactions for O'Chat channels
     * @override
     */
    canAddReaction(thread) {
        if (thread?.channel_type === "ochat") {
            return false;
        }
        return super.canAddReaction(thread);
    },
});
