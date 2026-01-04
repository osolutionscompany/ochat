/** @odoo-module **/

import { DiscussApp } from "@mail/core/public_web/discuss_app_model";
import { Record } from "@mail/core/common/record";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(DiscussApp, {
    new(data) {
        const res = super.new(data);
        res.ochat = {
            extraClass: "o-mail-DiscussSidebarCategory-ochat",
            icon: "fa fa-comments",  // Icône de chat pour O'Chat
            id: "ochat",
            name: _t("O'Chat"),
            hideWhenEmpty: true,
            canView: false,
            canAdd: false,  // Pas de bouton + (les channels sont créés automatiquement)
            serverStateKey: "is_discuss_sidebar_category_ochat_open",
            sequence: 25,  // Après WhatsApp (20)
        };
        return res;
    },
});

patch(DiscussApp.prototype, {
    setup(env) {
        super.setup(env);
        this.ochat = Record.one("DiscussAppCategory");
    },
});
