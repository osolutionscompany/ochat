/** @odoo-module **/

import { Message } from "@mail/core/common/message_model";
import { fields } from "@mail/core/common/record";
import { patch } from "@web/core/utils/patch";

/**
 * Patch du modèle Message pour ajouter les champs de statut O'Chat
 * V19: Declare fields in setup() method when patching
 */
patch(Message.prototype, {
    setup() {
        super.setup();
        this.ochat_fastapi_message_id = fields.Attr();
        this.ochat_delivery_status = fields.Attr();
        this.ochat_retry_count = fields.Attr();
        this.ochat_failed_reason = fields.Attr();
        this.ochat_delivered_at = fields.Attr();
        this.ochat_read_at = fields.Attr();
    },
});
