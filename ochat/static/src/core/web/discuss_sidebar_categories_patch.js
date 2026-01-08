/** @odoo-module **/

import { discussSidebarCategoriesRegistry } from "@mail/discuss/core/web/discuss_sidebar_categories";

// Register the O'Chat category in the sidebar
discussSidebarCategoriesRegistry.add(
    "ochat",
    { value: (store) => store.discuss.ochat },
    { sequence: 25 }  // After channels (10) and before chats (30)
);
