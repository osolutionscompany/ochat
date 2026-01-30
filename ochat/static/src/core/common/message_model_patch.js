/* @odoo-module */

import { Message as MessageModel } from "@mail/core/common/message_model";
import { Message as MessageComponent } from "@mail/core/common/message";
import { patch } from "@web/core/utils/patch";

/**
 * Patch du modèle Message pour ajouter les champs de statut O'Chat
 */
patch(MessageModel.prototype, {
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
        if (this.originThread?.type === "ochat") {
            return false;
        }
        return super.editable;
    },
});

/**
 * Patch du composant Message pour désactiver certaines fonctionnalités sur les channels O'Chat
 */
patch(MessageComponent.prototype, {
    /**
     * Disable reply for O'Chat channels
     * @override
     */
    get canReplyTo() {
        if (this.props.thread?.type === "ochat") {
            return false;
        }
        return super.canReplyTo;
    },

    /**
     * Disable reactions for O'Chat channels
     * @override
     */
    get canAddReaction() {
        if (this.props.thread?.type === "ochat") {
            return false;
        }
        return super.canAddReaction;
    },
});
