/** @odoo-module **/

import { DiscussApp } from "@mail/core/public_web/discuss_app_model";
import { fields } from "@mail/core/common/record";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(DiscussApp.prototype, {
    setup(env) {
        super.setup(...arguments);
        this.ochat = fields.One("DiscussAppCategory", {
            compute() {
                return {
                    extraClass: "o-mail-DiscussSidebarCategory-ochat",
                    hideWhenEmpty: true,
                    icon: "fa fa-comments",
                    id: "ochat",
                    name: _t("O'Chat"),
                    canView: false,
                    canAdd: false,
                    sequence: 25,
                    serverStateKey: "is_discuss_sidebar_category_ochat_open",
                };
            },
            eager: true,
        });
    },
});
