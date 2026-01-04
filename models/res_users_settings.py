from odoo import fields, models


class ResUsersSettings(models.Model):
    _inherit = 'res.users.settings'

    is_discuss_sidebar_category_ochat_open = fields.Boolean(
        string="O'Chat Category Open",
        default=True,
        help="If checked, the O'Chat category is open in the discuss sidebar"
    )
