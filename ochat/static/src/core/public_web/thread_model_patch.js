/** @odoo-module **/

import { Thread } from "@mail/core/common/thread_model";
import { patch } from "@web/core/utils/patch";

const threadPatch = {
    _computeDiscussAppCategory() {
        return this.channel_type === "ochat"
            ? this.store.discuss.ochat
            : super._computeDiscussAppCategory();
    },

    get avatarUrl() {
        // For O'Chat channels, show the correspondent's avatar (partner avatar)
        if (this.channel_type === "ochat" && this.correspondent) {
            return this.correspondent.avatarUrl;
        }
        return super.avatarUrl;
    },
};

patch(Thread.prototype, threadPatch);
