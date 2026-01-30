/* @odoo-module */

import { Thread } from "@mail/core/common/thread_model";
import { assignDefined } from "@mail/utils/common/misc";
import { patch } from "@web/core/utils/patch";
import { url } from "@web/core/utils/urls";

patch(Thread.prototype, {
    update(data) {
        super.update(...arguments);
        // Add ochat threads to the ochat category
        if (this.type === "ochat" && this._store.discuss?.ochat) {
            this._store.discuss.ochat.threads.add(this);
        }
    },

    /**
     * Override imgUrl to show the correspondent's avatar for O'Chat channels
     * Similar to how chat type shows the chatPartner's avatar
     */
    get imgUrl() {
        if (this.type === "ochat" && this.correspondent) {
            return url(
                `/web/image/res.partner/${this.correspondent.id}/avatar_128`,
                assignDefined({}, { unique: this.correspondent.write_date })
            );
        }
        return super.imgUrl;
    },
});
