import logging
import json

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class OchatWebhook(http.Controller):

    @http.route('/o_chat/webhook', type='json', auth='none', methods=['POST'], csrf=False)
    def receive_message(self, **kwargs):
        """
        Endpoint webhook pour recevoir les messages du serveur central
        """
        try:
            data = json.loads(request.httprequest.data)
            _logger.info(f"📨 Received message from central server: {data}")

            # Récupérer les informations du message
            source_uuid = data.get('source_instance_uuid')
            content = data.get('content')
            message_id = data.get('message_id')
            attachments_data = data.get('attachments', [])

            if not source_uuid:
                _logger.error(f"❌ Missing required field: source_uuid")
                return {
                    'status': 'error',
                    'message': 'Missing required field: source_uuid'
                }

            # Créer un environnement Odoo avec l'utilisateur admin
            env = request.env(user=1)  # user=1 est généralement l'admin

            # Trouver ou créer le canal de discussion
            connection_model = env['ochat.connection']
            channel = connection_model._find_or_create_channel(source_uuid)

            if not channel:
                _logger.error(f"❌ Could not create/find channel for instance {source_uuid}")
                return {
                    'status': 'error',
                    'message': 'Could not find connection'
                }

            # Récupérer le partner de la connection pour l'utiliser comme auteur
            connection = env['ochat.connection'].search([
                ('remote_instance_uuid', '=', source_uuid)
            ], limit=1)

            author_id = connection.partner_id.id if connection and connection.partner_id else None

            # Créer les pièces jointes si présentes
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

            # Poster le message dans le channel
            # IMPORTANT: ochat_incoming=True pour éviter la boucle infinie
            message = channel.message_post(
                body=content or '',  # Permettre messages vides avec attachments
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                author_id=author_id,  # Utiliser le partner de la connection comme auteur
                attachment_ids=[(6, 0, attachment_ids)] if attachment_ids else [],  # Lier les attachments
                ochat_incoming=True,  # Flag pour éviter de renvoyer ce message
            )

            # Notifier tous les membres pour faire "pop" le message
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
