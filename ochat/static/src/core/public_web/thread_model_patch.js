/** @odoo-module **/

import { Thread } from "@mail/core/common/thread_model";
import { patch } from "@web/core/utils/patch";

patch(Thread.prototype, {
    update(data) {
        super.update(data);
        // Add ochat threads to the ochat category
        if (this.type === "ochat" && this._store.discuss?.ochat) {
            this._store.discuss.ochat.threads.add(this);
        }
    },
});
