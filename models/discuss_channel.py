import logging
import base64
import requests
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    """Extend discuss.channel to support O'Chat channel type"""
    _inherit = 'discuss.channel'

    channel_type = fields.Selection(
        selection_add=[('ochat', "O'Chat Conversation")],
        ondelete={'ochat': 'cascade'}
    )
    ochat_connection_id = fields.Many2one(
        'ochat.connection',
        string="O'Chat Connection",
        index='btree_not_null'
    )

    @api.constrains('channel_type', 'ochat_connection_id')
    def _check_ochat_connection(self):
        """Ensure O'Chat channels have a connection"""
        missing_connection = self.filtered(
            lambda channel: channel.channel_type == 'ochat' and not channel.ochat_connection_id
        )
        if missing_connection:
            raise ValidationError(
                _("An O'Chat connection is required for O'Chat channels %(channel_names)s",
                  channel_names=', '.join(missing_connection.mapped('name')))
            )

    def message_post(self, **kwargs):
        """Override message_post to send O'Chat messages via central server"""
        self.ensure_one()

        # Vérifier si c'est un message entrant (depuis le webhook)
        # Ces messages ne doivent PAS être renvoyés au serveur central
        ochat_incoming = kwargs.pop('ochat_incoming', False)

        # Si c'est un canal O'Chat ET ce n'est pas un message entrant
        if self.channel_type == 'ochat' and self.ochat_connection_id and not ochat_incoming:
            # D'abord créer le message localement
            message = super().message_post(**kwargs)

            # Ensuite l'envoyer via O'Chat avec les attachments
            try:
                self._send_ochat_message(
                    content=kwargs.get('body', ''),
                    message=message
                )
            except Exception as e:
                _logger.error(f"❌ Failed to send O'Chat message: {str(e)}")
                # Le message reste visible localement même si l'envoi échoue

            return message

        # Pour les autres types de canaux, comportement normal
        return super().message_post(**kwargs)

    def _send_ochat_message(self, content, message=None):
        """Send message to remote instance via central server"""
        self.ensure_one()

        if not self.ochat_connection_id:
            raise UserError(_("No O'Chat connection linked to this channel"))

        # Récupérer la configuration O'Chat
        ICP = self.env['ir.config_parameter'].sudo()
        instance_uuid = ICP.get_param('ochat.instance_uuid')
        central_server_url = ICP.get_param('ochat.central_server_url')

        if not instance_uuid or not central_server_url:
            raise UserError(_("O'Chat is not properly configured"))

        # Préparer les pièces jointes si présentes
        attachments = []
        if message and message.attachment_ids:
            for attachment in message.attachment_ids:
                # Encoder chaque pièce jointe en base64
                attachments.append({
                    'name': attachment.name,
                    'mimetype': attachment.mimetype,
                    'datas': attachment.datas.decode('utf-8') if isinstance(attachment.datas, bytes) else attachment.datas,
                })
                _logger.info(f"📎 Preparing attachment: {attachment.name} ({attachment.mimetype})")

        # Préparer les données du message
        data = {
            'source_instance_uuid': instance_uuid,
            'target_instance_uuid': self.ochat_connection_id.remote_instance_uuid,
            'content': content,
            'attachments': attachments,
        }

        # Envoyer via le serveur central
        response = requests.post(
            f"{central_server_url}/api/v1/messages/send",
            json=data,
            timeout=30  # Augmenté à 30s pour les fichiers volumineux
        )

        if response.status_code != 200:
            raise UserError(
                _("Failed to send O'Chat message: %(status)s - %(text)s",
                  status=response.status_code,
                  text=response.text)
            )

        _logger.info(f"✅ O'Chat message sent to {self.ochat_connection_id.name} with {len(attachments)} attachment(s)")

    def _notify_ochat_incoming_message(self):
        """
        Notify all channel members about incoming O'Chat message
        Ensures the channel pops up in their Discuss interface
        """
        self.ensure_one()

        if self.channel_type != 'ochat':
            return

        # Re-pin the channel for all members and mark as unread
        for member in self.channel_member_ids:
            member.write({
                'unpin_dt': False,  # Re-pin if unpinned
                'last_interest_dt': fields.Datetime.now(),  # Update interest timestamp
            })

        # Broadcast to all members to refresh their Discuss UI
        self._broadcast(self.channel_member_ids.partner_id.ids)

        _logger.info(f"✅ Broadcast notification sent to {len(self.channel_member_ids)} member(s) of channel {self.name}")
