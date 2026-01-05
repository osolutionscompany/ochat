import uuid
import requests
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .crypto_helper import generate_rsa_keypair

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # O'Chat Configuration fields
    ochat_instance_uuid = fields.Char(
        string='Instance UUID',
        config_parameter='ochat.instance_uuid',
        readonly=True,
    )
    ochat_instance_name = fields.Char(
        string='Instance Name',
        config_parameter='ochat.instance_name',
    )
    ochat_central_server_url = fields.Char(
        string='Central Server URL',
        config_parameter='ochat.central_server_url',
        default='http://localhost:8000',
    )
    ochat_is_registered = fields.Boolean(
        string='Is Registered',
        config_parameter='ochat.is_registered',
        readonly=True,
    )

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        ICP = self.env['ir.config_parameter'].sudo()

        # Générer un UUID si non existant
        instance_uuid = ICP.get_param('ochat.instance_uuid')
        if not instance_uuid:
            instance_uuid = str(uuid.uuid4())
            ICP.set_param('ochat.instance_uuid', instance_uuid)

        res.update(
            ochat_instance_uuid=instance_uuid,
            ochat_instance_name=ICP.get_param('ochat.instance_name', ''),
            ochat_central_server_url=ICP.get_param('ochat.central_server_url', 'http://localhost:8000'),
            ochat_is_registered=ICP.get_param('ochat.is_registered', 'False') == 'True',
        )
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        ICP = self.env['ir.config_parameter'].sudo()

        ICP.set_param('ochat.instance_name', self.ochat_instance_name or '')
        ICP.set_param('ochat.central_server_url', self.ochat_central_server_url or 'http://localhost:8000')

    def action_ochat_register(self):
        """Enregistre cette instance auprès du serveur central"""
        self.ensure_one()

        ICP = self.env['ir.config_parameter'].sudo()

        # Récupérer l'URL de base d'Odoo
        base_url = ICP.get_param('web.base.url')
        webhook_url = f"{base_url}/o_chat/webhook"

        instance_uuid = ICP.get_param('ochat.instance_uuid')
        instance_name = self.ochat_instance_name
        central_server_url = self.ochat_central_server_url

        if not instance_name:
            raise UserError(_("Please set an Instance Name before registering."))

        # Générer une paire de clés RSA pour le chiffrement E2E
        _logger.info("🔐 Generating RSA keypair for encryption...")
        private_key_pem, public_key_pem = generate_rsa_keypair()

        # Stocker la clé privée localement (jamais partagée!)
        ICP.set_param('ochat.private_key', private_key_pem)
        _logger.info("🔑 Private key stored securely")

        # Préparer les données d'enregistrement avec la clé publique
        data = {
            'uuid': instance_uuid,
            'name': instance_name,
            'domain': base_url,
            'webhook_url': webhook_url,
            'public_key': public_key_pem  # Envoyer la clé publique au serveur
        }

        try:
            # Envoyer la requête d'enregistrement
            response = requests.post(
                f"{central_server_url}/api/v1/instances/register",
                json=data,
                timeout=10
            )

            if response.status_code == 200:
                # Récupérer et stocker l'API key et le webhook secret retournés par le serveur
                response_data = response.json()
                api_key = response_data.get('api_key')
                webhook_secret = response_data.get('webhook_secret')

                if api_key:
                    ICP.set_param('ochat.api_key', api_key)
                    _logger.info(f"🔑 API key received and stored")
                else:
                    _logger.warning("⚠️ No API key in registration response")

                if webhook_secret:
                    ICP.set_param('ochat.webhook_secret', webhook_secret)
                    _logger.info(f"🔐 Webhook secret received and stored")
                else:
                    _logger.warning("⚠️ No webhook secret in registration response")

                ICP.set_param('ochat.is_registered', 'True')
                # Recharger les valeurs
                self.ochat_is_registered = True
                _logger.info(f"✅ Successfully registered instance {instance_name} with central server")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Success'),
                        'message': _('Instance successfully registered with central server!'),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                _logger.error(f"❌ Failed to register: {response.status_code} - {response.text}")
                raise UserError(f"Registration failed: {response.status_code}")

        except requests.exceptions.RequestException as e:
            _logger.error(f"❌ Connection error during registration: {str(e)}")
            raise UserError(f"Could not connect to central server: {str(e)}")
