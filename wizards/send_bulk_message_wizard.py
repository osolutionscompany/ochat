# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import html2plaintext, plaintext2html


class SendBulkMessageWizard(models.TransientModel):
    _name = 'ochat.send.bulk.message.wizard'
    _description = 'Send Message to Multiple O\'Chat Connections'

    connection_ids = fields.Many2many(
        'ochat.connection',
        string='Connections',
        required=True,
        help='O\'Chat connections that will receive the message'
    )
    message = fields.Text(
        string='Message',
        required=True,
        help='Message to send to all selected connections'
    )
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'ochat_bulk_message_attachment_rel',
        'wizard_id',
        'attachment_id',
        string='Attachments'
    )

    @api.model
    def default_get(self, fields_list):
        """Pre-fill connections from context"""
        res = super().default_get(fields_list)

        # Get connection IDs from context (selected records)
        connection_ids = self.env.context.get('active_ids', [])
        if connection_ids:
            res['connection_ids'] = [(6, 0, connection_ids)]

        return res

    def action_send_message(self):
        """Send the message to all selected connections"""
        self.ensure_one()

        if not self.connection_ids:
            raise UserError(_('Please select at least one connection'))

        if not self.message:
            raise UserError(_('Please enter a message'))

        sent_count = 0
        failed_connections = []

        # Extract plain text from HTML (removes all HTML tags and entities)
        # then convert back to clean HTML
        message_body = html2plaintext(self.message)

        for connection in self.connection_ids:
            try:
                # Get or create channel for this connection
                channel = self.env['discuss.channel'].search([
                    ('channel_type', '=', 'ochat'),
                    ('ochat_connection_id', '=', connection.id)
                ], limit=1)

                if not channel:
                    # Create channel if it doesn't exist
                    channel = self.env['discuss.channel'].create({
                        'name': connection.name,
                        'channel_type': 'ochat',
                        'ochat_connection_id': connection.id,
                    })

                # Post message with attachments
                channel.message_post(
                    body=message_body,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                    attachment_ids=self.attachment_ids.ids if self.attachment_ids else []
                )
                sent_count += 1

            except Exception as e:
                failed_connections.append(f"{connection.name}: {str(e)}")

        # Show result message and close wizard
        if failed_connections:
            message = _('Message sent to %(sent)s connection(s).\n\nFailed connections:\n%(failed)s',
                       sent=sent_count,
                       failed='\n'.join(failed_connections))
            raise UserError(message)

        # Show success notification and close wizard
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Message sent to %s connection(s)') % sent_count,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
