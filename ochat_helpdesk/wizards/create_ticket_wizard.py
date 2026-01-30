# -*- coding: utf-8 -*-
"""
Wizard to create a helpdesk ticket from O'Chat conversation
"""
from markupsafe import Markup, escape

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class CreateTicketWizard(models.TransientModel):
    _name = 'ochat.create.ticket.wizard'
    _description = 'Create Helpdesk Ticket from O\'Chat'

    channel_id = fields.Many2one(
        'discuss.channel',
        string='Channel',
        required=True,
        readonly=True,
        ondelete='cascade'
    )

    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        help='The customer for this ticket'
    )

    team_id = fields.Many2one(
        'helpdesk.team',
        string='Helpdesk Team',
        required=True,
        help='The helpdesk team responsible for this ticket'
    )

    user_id = fields.Many2one(
        'res.users',
        string='Assigned To',
        help='User assigned to this ticket'
    )

    name = fields.Char(
        string='Subject',
        required=True,
        default='Ticket from O\'Chat conversation'
    )

    description = fields.Html(
        string='Description',
        help='Detailed description of the issue'
    )

    tag_ids = fields.Many2many(
        'helpdesk.tag',
        string='Tags',
        help='Tags to categorize this ticket'
    )

    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Medium'),
        ('2', 'High'),
        ('3', 'Urgent')
    ], string='Priority', default='1')

    @api.model
    def default_get(self, fields_list):
        """Set default values from context"""
        res = super().default_get(fields_list)

        # Get channel from context
        channel_id = self.env.context.get('default_channel_id')
        if channel_id:
            channel = self.env['discuss.channel'].browse(channel_id)
            res['channel_id'] = channel_id

            # Set partner from O'Chat connection
            if channel.ochat_connection_id and channel.ochat_connection_id.partner_id:
                res['partner_id'] = channel.ochat_connection_id.partner_id.id

        # Set default team (first available)
        if 'team_id' in fields_list and not res.get('team_id'):
            default_team = self.env['helpdesk.team'].search([], limit=1)
            if default_team:
                res['team_id'] = default_team.id

        return res

    def action_create_ticket(self):
        """Create the helpdesk ticket"""
        self.ensure_one()

        # Create the ticket
        ticket = self.env['helpdesk.ticket'].create({
            'name': self.name,
            'partner_id': self.partner_id.id,
            'team_id': self.team_id.id,
            'user_id': self.user_id.id if self.user_id else False,
            'description': self.description,
            'tag_ids': [(6, 0, self.tag_ids.ids)],
            'priority': self.priority,
        })

        # Build message body with or without portal link
        if hasattr(ticket, 'get_portal_url'):
            # Portal module is installed - include link with access token
            ticket._portal_ensure_token()
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            ticket_url = base_url + ticket.get_portal_url()
            message_body = Markup(
                'A support ticket has been created: '
                '<a href="%s">%s</a>'
            ) % (ticket_url, escape(ticket.name))
        else:
            # Portal module not installed - just mention ticket name
            message_body = 'A support ticket has been created: %s' % ticket.name

        # Send message to the O'Chat channel
        self.channel_id.message_post(
            body=message_body,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

        # Return action to open the created ticket
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'helpdesk.ticket',
            'res_id': ticket.id,
            'view_mode': 'form',
            'target': 'current',
        }
