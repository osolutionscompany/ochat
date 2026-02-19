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
    otokens_key = fields.Char(
        string="O'tokens Key",
        config_parameter='o_tokens.key',
    )

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        ICP = self.env['ir.config_parameter'].sudo()

        # Generate a UUID if it doesn't exist
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
        """Registers this instance with the central server"""
        self.ensure_one()

        # Automatically save the configuration settings first
        self.set_values()

        ICP = self.env['ir.config_parameter'].sudo()

        # Retrieve Odoo's base URL
        base_url = ICP.get_param('web.base.url')
        webhook_url = f"{base_url}/ochat/webhook"

        instance_uuid = ICP.get_param('ochat.instance_uuid')
        instance_name = self.ochat_instance_name
        central_server_url = self.ochat_central_server_url

        if not instance_name:
            raise UserError(_("Please set an Instance Name before registering."))

        # Generate an RSA keypair for E2E encryption
        _logger.info("🔐 Generating RSA keypair for encryption...")
        private_key_pem, public_key_pem = generate_rsa_keypair()

        # Store the private key locally (never shared!)
        ICP.set_param('ochat.private_key', private_key_pem)
        _logger.info("🔑 Private key stored securely")

        # Prepare registration data with the public key
        data = {
            'uuid': instance_uuid,
            'name': instance_name,
            'domain': base_url,
            'webhook_url': webhook_url,
            'public_key': public_key_pem  # Send the public key to the server
        }

        try:
            # Préparer les headers - inclure l'API key existante pour le ré-enregistrement
            headers = {'Content-Type': 'application/json'}
            existing_api_key = ICP.get_param('ochat.api_key')
            if existing_api_key:
                headers['Authorization'] = f'Bearer {existing_api_key}'

            # Envoyer la requête d'enregistrement
            response = requests.post(
                f"{central_server_url}/api/v1/instances/register",
                json=data,
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                # Retrieve and store the API key and webhook secret returned by the server
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
                # Reload the values
                self.ochat_is_registered = True
                _logger.info(f"✅ Successfully registered instance {instance_name} with central server")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                }
            else:
                _logger.error(f"❌ Failed to register: {response.status_code} - {response.text}")
                raise UserError(f"Registration failed: {response.status_code}")

        except requests.exceptions.RequestException as e:
            _logger.error(f"❌ Connection error during registration: {str(e)}")
            raise UserError(f"Could not connect to central server: {str(e)}")
