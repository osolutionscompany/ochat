/** @odoo-module **/

import { Thread } from "@mail/core/common/thread_model";
import { patch } from "@web/core/utils/patch";

patch(Thread.prototype, {
    _computeDiscussAppCategory() {
        return this.channel_type === "ochat"
            ? this.store.discuss.ochat
            : super._computeDiscussAppCategory();
    },
});
