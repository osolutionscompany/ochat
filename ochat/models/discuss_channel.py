import logging
import base64
import requests
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools import html_escape
from markupsafe import Markup
from .crypto_helper import encrypt_message_hybrid
from odoo.tools import html2plaintext


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
    ochat_remote_instance_uuid = fields.Char(
        string="Remote Instance UUID",
        help="UUID of the remote instance. Used to find existing channels when recreating a connection.",
        index=True
    )

    @api.constrains('channel_type', 'ochat_remote_instance_uuid')
    def _check_ochat_connection(self):
        """Ensure O'Chat channels have a remote instance UUID"""
        missing_uuid = self.filtered(
            lambda channel: channel.channel_type == 'ochat' and not channel.ochat_remote_instance_uuid
        )
        if missing_uuid:
            raise ValidationError(
                _("A remote instance UUID is required for O'Chat channels %(channel_names)s",
                  channel_names=', '.join(missing_uuid.mapped('name')))
            )

    def message_post(self, **kwargs):
        """Override message_post to send O'Chat messages via central server"""
        self.ensure_one()

        # Check if this is an incoming message (from webhook)
        # These messages should NOT be sent back to the central server
        ochat_incoming = kwargs.pop('ochat_incoming', False)

        # If this is an O'Chat channel AND not an incoming message
        if self.channel_type == 'ochat' and self.ochat_connection_id and not ochat_incoming:
            # Create the message first
            # We'll send our own notification after adding O'Chat fields
            message = super().message_post(**kwargs)

            # Commit to ensure the message exists in DB before sending
            self.env.cr.commit()

            # Then send it via O'Chat with attachments
            try:
                self._send_ochat_message(
                    content=kwargs.get('body', ''),
                    message=message
                )
            except Exception as e:
                _logger.error(f"❌ Failed to send O'Chat message: {str(e)}")
                # Message remains visible locally even if sending fails

            return message

        # For other channel types, use normal behavior
        return super().message_post(**kwargs)

    def _send_ochat_message(self, content, message=None):
        """Send message to remote instance via central server"""
        self.ensure_one()

        if not self.ochat_connection_id:
            raise UserError(_("No O'Chat connection linked to this channel"))

        # Get O'Chat configuration
        ICP = self.env['ir.config_parameter'].sudo()
        instance_uuid = ICP.get_param('ochat.instance_uuid')
        central_server_url = ICP.get_param('ochat.central_server_url')
        api_key = ICP.get_param('ochat.api_key')

        if not instance_uuid or not central_server_url:
            raise UserError(_("O'Chat is not properly configured"))

        if not api_key:
            raise UserError(_("Missing API key. Please re-register this instance."))

        # Prepare attachments if present
        attachments = []
        if message and message.attachment_ids:
            max_size_mb = 100
            max_size_bytes = max_size_mb * 1024 * 1024

            for attachment in message.attachment_ids:
                # Vérifier la taille du fichier (file_size est en bytes)
                if attachment.file_size and attachment.file_size > max_size_bytes:
                    size_mb = attachment.file_size / (1024 * 1024)
                    raise UserError(
                        _("Cannot send file '%(filename)s': file size (%(size).1f MB) exceeds the maximum allowed size of %(max)d MB.",
                          filename=attachment.name,
                          size=size_mb,
                          max=max_size_mb)
                    )

                # En Odoo, attachment.datas est déjà en base64 (string)
                # Il faut juste s'assurer que c'est bien une string
                datas_b64 = attachment.datas
                if isinstance(datas_b64, bytes):
                    datas_b64 = datas_b64.decode('utf-8')

                attachments.append({
                    'name': attachment.name,
                    'mimetype': attachment.mimetype,
                    'datas': datas_b64,
                })
                _logger.info(f"📎 Preparing attachment: {attachment.name} ({attachment.mimetype}, size: {len(datas_b64)} chars)")

        # Get recipient's public key
        try:
            public_key_response = requests.get(
                f"{central_server_url}/api/v1/instances/{self.ochat_connection_id.remote_instance_uuid}/public_key",
                timeout=10
            )
            if public_key_response.status_code != 200:
                raise UserError(_("Could not retrieve recipient's public key"))

            recipient_public_key = public_key_response.json().get('public_key')
            if not recipient_public_key:
                raise UserError(_("Recipient has no public key configured"))

        except requests.exceptions.RequestException as e:
            raise UserError(f"Failed to fetch recipient's public key: {str(e)}")

        # Encrypt message and attachments with recipient's public key
        _logger.info("🔒 Encrypting message before sending...")
        encrypted_data = encrypt_message_hybrid(content, attachments, recipient_public_key)

        # Prepare message data (now encrypted)
        data = {
            'source_instance_uuid': instance_uuid,
            'target_instance_uuid': self.ochat_connection_id.remote_instance_uuid,
            'encrypted_data': encrypted_data
        }

        # Prepare headers with authentication
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        # Send via central server
        response = requests.post(
            f"{central_server_url}/api/v1/messages/send",
            json=data,
            headers=headers,
            timeout=30  # Increased to 30s for large files
        )

        if response.status_code != 200:
            # Parser le JSON pour extraire le message détaillé
            error_message = response.text
            try:
                error_data = response.json()
                if 'detail' in error_data:
                    error_message = error_data['detail']
            except:
                pass

            _logger.error(f"❌ Failed to send message: {response.status_code} - {response.text}")
            raise UserError(
                _("Failed to send O'Chat message: %s", error_message)
            )

        # Get the FastAPI message ID from response
        response_data = response.json()
        fastapi_message_id = response_data.get('id')

        if fastapi_message_id and message:
            # Store FastAPI ID in Odoo message for tracking
            message.write({
                'ochat_fastapi_message_id': fastapi_message_id,
                'ochat_delivery_status': 'pending'
            })

            # Force immediate commit to ensure data is in DB
            self.env.cr.commit()

            # Send bus notification to update interface in real-time
            try:
                # Get complete formatted message with all O'Chat fields
                formatted_messages = message.message_format()
                if formatted_messages:
                    # Send complete message update to all channel members
                    notifications = []
                    for member in self.channel_member_ids:
                        if member.partner_id:
                            notifications.append([
                                member.partner_id,
                                'mail.record/insert',
                                {'Message': [formatted_messages[0]]}
                            ])

                    if notifications:
                        self.env['bus.bus']._sendmany(notifications)
                        _logger.info(f"✅ Sent initial O'Chat status notification for message {message.id}")

            except Exception as e:
                _logger.warning(f"Could not send initial status notification: {e}")

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
                'is_pinned': True,  # Re-pin if unpinned
                'last_interest_dt': fields.Datetime.now(),  # Update interest timestamp
            })

        # Broadcast to all members to refresh their Discuss UI
        self._broadcast(self.channel_member_ids.partner_id.ids)

        _logger.info(f"✅ Broadcast notification sent to {len(self.channel_member_ids)} member(s) of channel {self.name}")

    def execute_command_help(self, **kwargs):
        """Override /help command to add O'Chat specific commands"""
        self.ensure_one()
        if self.channel_type == 'ochat':
            # Custom help for O'Chat channels
            msg = Markup(_(
                "<b>Available commands for O'Chat:</b><br/>"
                "• <b>/help</b>: Show this help message<br/>"
                "• <b>/leave</b>: Leave this conversation<br/>"
                "• <b>/status</b>: Show connection status and encryption info<br/>"
                "• <b>/who</b>: List members in this conversation"
            ))
            self.env.user._bus_send_transient_message(self, msg)
        else:
            # Default help for other channels
            return super().execute_command_help(**kwargs)

    def execute_command_status(self, **kwargs):
        """Custom O'Chat command: /status - Shows connection info"""
        self.ensure_one()

        if self.channel_type != 'ochat':
            return

        if not self.ochat_connection_id:
            msg = Markup(_("⚠️ This channel has no O'Chat connection"))
        else:
            connection = self.ochat_connection_id
            ICP = self.env['ir.config_parameter'].sudo()

            # Encryption status
            encryption_status = "🔒 Enabled"

            # Connection status based on status field
            status_display = {
                'active': '🟢 Active',
                'pending': '🟡 Pending',
                'blocked': '🔴 Blocked',
            }.get(connection.status, '⚪ Unknown')

            msg = Markup(_(
                "<b>O'Chat Connection Status</b><br/>"
                "• <b>Remote Instance:</b> %(instance_name)s<br/>"
                "• <b>Instance ID:</b> %(instance_uuid)s<br/>"
                "• <b>Status:</b> %(status)s<br/>"
                "• <b>Encryption:</b> %(encryption)s"
            )) % {
                'instance_name': html_escape(connection.name or 'Unknown'),
                'instance_uuid': html_escape(connection.remote_instance_uuid),
                'status': status_display,
                'encryption': encryption_status,
            }

        # Send as transient message (not saved)
        self.env.user._bus_send_transient_message(self, msg)
