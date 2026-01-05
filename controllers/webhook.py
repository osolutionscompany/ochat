import logging
import json

from odoo import http
from odoo.http import request
from odoo.addons.o_chat.models.crypto_helper import decrypt_message_hybrid

_logger = logging.getLogger(__name__)


class OchatWebhook(http.Controller):

    @http.route('/o_chat/webhook', type='json', auth='none', methods=['POST'], csrf=False)
    def receive_message(self, **kwargs):
        """
        Endpoint webhook pour recevoir les messages du serveur central
        """
        try:
            # Vérifier l'authentification
            authorization = request.httprequest.headers.get('Authorization')
            if not authorization:
                _logger.error("❌ Missing Authorization header in webhook call")
                return {
                    'status': 'error',
                    'message': 'Missing Authorization header'
                }

            # Récupérer le webhook secret stocké
            ICP = request.env['ir.config_parameter'].sudo()
            expected_secret = ICP.get_param('ochat.webhook_secret')

            if not expected_secret:
                _logger.error("❌ No webhook secret configured")
                return {
                    'status': 'error',
                    'message': 'Webhook not configured'
                }

            # Vérifier le token
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

            # Authentification réussie, traiter le message
            data = json.loads(request.httprequest.data)
            _logger.info(f"📨 Received authenticated message from central server")

            # Récupérer les informations du message
            source_uuid = data.get('source_instance_uuid')
            message_id = data.get('message_id')

            # Vérifier si le message est chiffré
            encrypted_data = data.get('encrypted_data')

            if encrypted_data:
                # Message chiffré - déchiffrer avec notre clé privée
                _logger.info(f"🔒 Encrypted message detected, decrypting...")

                # Récupérer notre clé privée
                ICP = request.env['ir.config_parameter'].sudo()
                private_key_pem = ICP.get_param('ochat.private_key')

                if not private_key_pem:
                    _logger.error("❌ No private key found - cannot decrypt message")
                    return {
                        'status': 'error',
                        'message': 'No private key configured'
                    }

                try:
                    # Déchiffrer le message
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
                # Message en clair (rétrocompatibilité)
                content = data.get('content')
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

    @http.route('/o_chat/webhook/status', type='json', auth='none', methods=['POST'], csrf=False)
    def receive_status_update(self, **kwargs):
        """
        Endpoint webhook pour recevoir les notifications de changement de statut
        Appelé par FastAPI quand le statut d'un message change
        """
        try:
            # Vérifier l'authentification
            authorization = request.httprequest.headers.get('Authorization')
            if not authorization:
                _logger.error("❌ Missing Authorization header in status webhook")
                return {
                    'status': 'error',
                    'message': 'Missing Authorization header'
                }

            # Récupérer le webhook secret
            ICP = request.env['ir.config_parameter'].sudo()
            expected_secret = ICP.get_param('ochat.webhook_secret')

            if not expected_secret:
                _logger.error("❌ No webhook secret configured")
                return {
                    'status': 'error',
                    'message': 'Webhook not configured'
                }

            # Vérifier le token
            provided_secret = authorization.replace('Bearer ', '')
            if provided_secret != expected_secret:
                _logger.error("❌ Invalid webhook secret in status update")
                return {
                    'status': 'error',
                    'message': 'Unauthorized'
                }

            # Récupérer les données de la requête
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

            # Créer un environnement Odoo avec l'utilisateur admin
            env = request.env(user=1)

            # Chercher le message mail correspondant dans Odoo
            # Le message_id de FastAPI est stocké dans le corps du message ou comme référence
            # Pour l'instant, on log juste la notification
            # TODO: Stocker le message_id FastAPI quelque part pour pouvoir retrouver le message Odoo

            _logger.info(
                f"📬 Status update received: Message {message_id} → {status} "
                f"(metadata: {metadata})"
            )

            # Afficher des logs différents selon le statut
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

            # TODO: Mettre à jour l'interface Odoo pour afficher le statut
            # Par exemple, ajouter une icône de statut sur le message dans Discuss

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
