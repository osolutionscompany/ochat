import logging
import json

from markupsafe import Markup
from odoo import http
from odoo.http import request
from odoo.addons.ochat.models.crypto_helper import decrypt_message_hybrid

_logger = logging.getLogger(__name__)


class OchatWebhook(http.Controller):

    @http.route('/ochat/webhook', type='json', auth='none', methods=['POST'], csrf=False)
    def receive_message(self, **kwargs):
        """
        Webhook endpoint to receive messages from the central server
        """
        try:
            # Check authentication
            authorization = request.httprequest.headers.get('Authorization')
            if not authorization:
                _logger.error("❌ Missing Authorization header in webhook call")
                return {
                    'status': 'error',
                    'message': 'Missing Authorization header'
                }

            # Retrieve stored webhook secret
            ICP = request.env['ir.config_parameter'].sudo()
            expected_secret = ICP.get_param('ochat.webhook_secret')

            if not expected_secret:
                _logger.error("❌ No webhook secret configured")
                return {
                    'status': 'error',
                    'message': 'Webhook not configured'
                }

            # Check token
            if not authorization.startswith('Bearer '):
                _logger.error("❌ Invalid Authorization header format")
                return {
                    'status': 'error',
                    'message': 'Invalid Authorization header format'
                }

            provided_secret = authorization.replace('Bearer ', '')
            if provided_secret != expected_secret:
                _logger.error(f"❌ Invalid webhook secret")
                return {
                    'status': 'error',
                    'message': 'Invalid webhook secret'
                }

            # Authentication successful, process message
            data = json.loads(request.httprequest.data)
            _logger.info(f"📨 Received authenticated message from central server")

            # Get message information
            source_uuid = data.get('source_instance_uuid')
            message_id = data.get('message_id')

            # Check if message is encrypted
            encrypted_data = data.get('encrypted_data')

            if encrypted_data:
                # Encrypted message - decrypt with our private key
                _logger.info(f"🔒 Encrypted message detected, decrypting...")

                # Get our private key
                ICP = request.env['ir.config_parameter'].sudo()
                private_key_pem = ICP.get_param('ochat.private_key')

                if not private_key_pem:
                    _logger.error("❌ No private key found - cannot decrypt message")
                    return {
                        'status': 'error',
                        'message': 'No private key configured'
                    }

                try:
                    # Decrypt message
                    decrypted = decrypt_message_hybrid(encrypted_data, private_key_pem)
                    content = decrypted.get('content', '')
                    attachments_data = decrypted.get('attachments', [])
                    _logger.info(f"✅ Message decrypted successfully")
                except Exception as e:
                    _logger.error(f"❌ Failed to decrypt message: {str(e)}")
                    return {
                        'status': 'error',
                        'message': f'Decryption failed: {str(e)}'
                    }
            else:
                # Plain text message (backward compatibility)
                content = data.get('content')
                attachments_data = data.get('attachments', [])

            if not source_uuid:
                _logger.error(f"❌ Missing required field: source_uuid")
                return {
                    'status': 'error',
                    'message': 'Missing required field: source_uuid'
                }

            # Create Odoo environment with admin user
            env = request.env(user=1)  # user=1 is usually admin

            # Find or create discussion channel
            connection_model = env['ochat.connection']
            channel = connection_model._find_or_create_channel(source_uuid)

            if not channel:
                _logger.error(f"❌ Could not create/find channel for instance {source_uuid}")
                return {
                    'status': 'error',
                    'message': 'Could not find connection'
                }

            # Get connection partner to use as author
            connection = env['ochat.connection'].search([
                ('remote_instance_uuid', '=', source_uuid)
            ], limit=1)

            author_id = connection.partner_id.id if connection and connection.partner_id else None

            # Create attachments if present
            attachment_ids = []
            if attachments_data:
                for att_data in attachments_data:
                    try:
                        attachment = env['ir.attachment'].create({
                            'name': att_data.get('name'),
                            'datas': att_data.get('datas'),
                            'mimetype': att_data.get('mimetype'),
                            'res_model': 'discuss.channel',
                            'res_id': channel.id,
                        })
                        attachment_ids.append(attachment.id)
                        _logger.info(f"📎 Created attachment: {attachment.name}")
                    except Exception as e:
                        _logger.error(f"❌ Failed to create attachment: {str(e)}")

            # Post message to channel
            # IMPORTANT: ochat_incoming=True to avoid infinite loop
            message = channel.message_post(
                body=Markup(content) if content else '',  # Markup pour interpréter le HTML
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                author_id=author_id,  # Use connection partner as author
                attachment_ids=attachment_ids if attachment_ids else [],  # Odoo 18: pass list of IDs directly
                ochat_incoming=True,  # Flag to avoid resending message
            )

            # Notify all members to "pop" the message
            channel._notify_ochat_incoming_message()

            _logger.info(f"✅ Message posted to channel '{channel.name}'")

            return {
                'status': 'received',
                'message': 'Message posted to Discuss channel successfully',
                'channel_id': channel.id
            }

        except Exception as e:
            _logger.error(f"❌ Error receiving message: {str(e)}")
            return {
                'status': 'error',
                'message': str(e)
            }

    @http.route('/ochat/webhook/status', type='json', auth='none', methods=['POST'], csrf=False)
    def receive_status_update(self, **kwargs):
        """
        Webhook endpoint to receive status change notifications
        Called by FastAPI when message status changes
        """
        try:
            # Check authentication
            authorization = request.httprequest.headers.get('Authorization')
            if not authorization:
                _logger.error("❌ Missing Authorization header in status webhook")
                return {
                    'status': 'error',
                    'message': 'Missing Authorization header'
                }

            # Get webhook secret
            ICP = request.env['ir.config_parameter'].sudo()
            expected_secret = ICP.get_param('ochat.webhook_secret')

            if not expected_secret:
                _logger.error("❌ No webhook secret configured")
                return {
                    'status': 'error',
                    'message': 'Webhook not configured'
                }

            # Check token
            provided_secret = authorization.replace('Bearer ', '')
            if provided_secret != expected_secret:
                _logger.error("❌ Invalid webhook secret in status update")
                return {
                    'status': 'error',
                    'message': 'Unauthorized'
                }

            # Get request data
            data = request.get_json_data()
            if not data:
                _logger.error("❌ No data in status update request")
                return {
                    'status': 'error',
                    'message': 'No data provided'
                }

            message_id = data.get('message_id')
            status = data.get('status')
            timestamp = data.get('timestamp')
            metadata = data.get('metadata', {})

            if not message_id or not status:
                _logger.error("❌ Missing required fields in status update")
                return {
                    'status': 'error',
                    'message': 'Missing required fields'
                }

            # Create Odoo environment with admin user
            env = request.env(user=1)

            # Update status of corresponding Odoo message
            mail_message_model = env['mail.message']
            updated = mail_message_model.update_ochat_status(
                fastapi_message_id=message_id,
                status=status,
                metadata=metadata
            )

            if updated:
                _logger.info(
                    f"📬 Status update received and applied: Message {message_id} → {status} "
                    f"(metadata: {metadata})"
                )
            else:
                _logger.warning(
                    f"⚠️  Status update received but message {message_id} not found in Odoo"
                )

            # Display different logs depending on status
            if status == 'delivered':
                retry_count = metadata.get('retry_count', 0)
                if retry_count > 0:
                    _logger.info(f"✅ Message {message_id} delivered after {retry_count} retries")
                else:
                    _logger.info(f"✅ Message {message_id} delivered on first attempt")

            elif status == 'read':
                read_at = metadata.get('read_at')
                _logger.info(f"👁️  Message {message_id} was read at {read_at}")

            elif status == 'failed':
                retry_count = metadata.get('retry_count', 0)
                error = metadata.get('error', 'Unknown error')
                _logger.warning(
                    f"❌ Message {message_id} failed definitively after {retry_count} attempts: {error}"
                )

            # TODO: Update Odoo interface to display status
            # For example, add status icon to message in Discuss

            return {
                'status': 'received',
                'message': f'Status update processed: {status}'
            }

        except Exception as e:
            _logger.error(f"❌ Error processing status update: {str(e)}")
            return {
                'status': 'error',
                'message': str(e)
            }
