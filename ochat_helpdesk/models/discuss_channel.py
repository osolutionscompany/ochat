# -*- coding: utf-8 -*-

from odoo import models, _


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def execute_command_ticket(self, **kwargs):
        """Custom O'Chat command: /ticket - Create a helpdesk ticket from conversation"""
        self.ensure_one()

        if self.channel_type != 'ochat':
            return

        # Return action to open the create ticket wizard
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Ticket from O\'Chat'),
            'res_model': 'ochat.create.ticket.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_channel_id': self.id,
            },
        }
