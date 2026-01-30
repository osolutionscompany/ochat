/* @odoo-module */

import { DiscussApp } from "@mail/core/common/discuss_app_model";
import { Record } from "@mail/core/common/record";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(DiscussApp, {
    new(data) {
        const res = super.new(data);
        Object.assign(res, {
            ochat: {
                extraClass: "o-mail-DiscussSidebarCategory-ochat",
                id: "ochat",
                name: _t("O'Chat"),
                isOpen: false,
                canView: false,
                canAdd: false,  // No + button (channels are created automatically)
                serverStateKey: "is_discuss_sidebar_category_ochat_open",
                addTitle: _t("O'Chat Conversations"),
                addHotkey: "o",
            },
        });
        return res;
    },
});

patch(DiscussApp.prototype, {
    setup() {
        super.setup(...arguments);
        this.ochat = Record.one("DiscussAppCategory");
    },
});
