{
    'name': "O'Chat",
    'version': '1.0',
    'category': 'Discuss',
    'summary': 'Inter-instance communication for Odoo',
    'depends': ['base', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/ochat_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'o_chat/static/src/core/public_web/discuss_app_model_patch.js',
            'o_chat/static/src/core/public_web/thread_model_patch.js',
            'o_chat/static/src/core/web/discuss_app_category_model_patch.js',
            'o_chat/static/src/core/common/thread_icon_patch.xml',
            'o_chat/static/src/core/web/discuss_sidebar_category_item_patch.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
