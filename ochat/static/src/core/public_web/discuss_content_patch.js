/** @odoo-module **/

import { DiscussContent } from "@mail/core/public_web/discuss_content";
import { patch } from "@web/core/utils/patch";

const discussContentPatch = {
    /**
     * Show avatar for O'Chat channels (partner avatar)
     * @override
     */
    get showThreadAvatar() {
        return ["channel", "group", "chat", "ochat"].includes(this.thread?.channel_type);
    },
};

patch(DiscussContent.prototype, discussContentPatch);
