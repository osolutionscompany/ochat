{
    'name': "O'Chat - Helpdesk Integration",
    'version': '1.0',
    'category': 'Discuss',
    'summary': 'Create helpdesk tickets from O\'Chat conversations',
    'depends': ['ochat', 'helpdesk'],
    'data': [
        'security/ir.model.access.csv',
        'views/create_ticket_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ochat_helpdesk/static/src/core/common/channel_commands_patch.js',
            'ochat_helpdesk/static/src/core/common/thread_service_patch.js',
        ],
    },
    'installable': True,
    'auto_install': True,
    'license': 'LGPL-3',
}
