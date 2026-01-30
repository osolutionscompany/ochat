{
    'name': "O'Chat",
    'version': '19.0.1.0.0',
    'category': 'Discuss',
    'summary': 'Inter-instance communication for Odoo',
    'depends': ['base', 'mail'],
    'external_dependencies': {
        'python': ['pycryptodome']
    },
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/res_config_settings_views.xml',
        'views/ochat_views.xml',
        'views/send_bulk_message_wizard_views.xml',
        'views/ochat_actions_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ochat/static/src/core/public_web/discuss_app_model_patch.js',
            'ochat/static/src/core/public_web/thread_model_patch.js',
            'ochat/static/src/core/public_web/discuss_content_patch.js',
            'ochat/static/src/core/web/discuss_app_category_model_patch.js',
            'ochat/static/src/core/common/message_model_patch.js',
            'ochat/static/src/core/common/channel_commands_patch.js',
            'ochat/static/src/core/common/thread_icon_patch.xml',
            'ochat/static/src/core/web/discuss_sidebar_category_item_patch.xml',
            'ochat/static/src/core/common/message_status.xml',
            'ochat/static/src/css/ochat_status.css',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
