import requests
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class OchatConnection(models.Model):
    _name = 'ochat.connection'
    _description = "O'Chat Connection"
    _rec_name = 'partner_id'

    partner_id = fields.Many2one(
        'res.partner',
        string='Contact',
        ondelete='cascade',
        copy=False
    )
    name = fields.Char(
        string='Name',
        related='partner_id.name',
        store=True,
        readonly=True
    )
    remote_instance_uuid = fields.Char(string='Remote Instance UUID', copy=False)
    status = fields.Selection([
        ('pending', 'Pending'),
        ('active', 'Active'),
        ('blocked', 'Blocked')
    ], string='Status', default='active')
    channel_id = fields.Many2one('discuss.channel', string='Discussion Channel')
    partner_ids = fields.Many2many(
        'res.partner',
        'ochat_connection_partner_rel',
        'connection_id',
        'partner_id',
        string='Additional Members',
        default=lambda self: [self.env.user.partner_id.id]
    )

    @api.constrains('partner_id', 'remote_instance_uuid')
    def _check_required_fields(self):
        """Ensure partner_id and remote_instance_uuid are filled when saving"""
        for connection in self:
            if not connection.partner_id:
                raise ValidationError(_("Contact is required and cannot be empty."))
            if not connection.remote_instance_uuid:
                raise ValidationError(_("Remote Instance UUID is required and cannot be empty."))

    @api.constrains('remote_instance_uuid')
    def _check_unique_remote_instance_uuid(self):
        """Ensure remote_instance_uuid is unique"""
        for connection in self:
            if connection.remote_instance_uuid:
                duplicate = self.search([
                    ('remote_instance_uuid', '=', connection.remote_instance_uuid),
                    ('id', '!=', connection.id)
                ], limit=1)
                if duplicate:
                    raise ValidationError(
                        _("A connection with remote instance UUID '%(uuid)s' already exists: %(name)s",
                          uuid=connection.remote_instance_uuid,
                          name=duplicate.name)
                    )

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to automatically create channel and sync members"""
        connections = super().create(vals_list)

        for connection in connections:
            # Créer automatiquement le canal O'Chat
            if not connection.channel_id:
                channel = self.env['discuss.channel'].create({
                    'name': f"{connection.name}",
                    'description': f"Inter-instance communication with {connection.name}",
                    'channel_type': 'ochat',
                    'ochat_connection_id': connection.id,
                })
                connection.channel_id = channel.id
                _logger.info(f"✅ Auto-created O'Chat channel for new connection {connection.name}")

            # Synchroniser les partners (principal + additionnels)
            connection._sync_channel_members()

        return connections

    def write(self, vals):
        """Override write to sync channel members when partners change"""
        res = super().write(vals)

        # Re-sync si le partner principal ou les membres additionnels changent
        if 'partner_id' in vals or 'partner_ids' in vals:
            self._sync_channel_members()

        return res

    def _sync_channel_members(self):
        """Synchronize discuss.channel.member with partner_id + partner_ids"""
        for connection in self:
            if not connection.channel_id:
                continue

            # Tous les partners à inclure : principal + additionnels (qui inclut maintenant le créateur)
            all_partners = connection.partner_id | connection.partner_ids

            # Récupérer les membres actuels du channel
            current_members = connection.channel_id.channel_member_ids
            current_partner_ids = current_members.mapped('partner_id')

            # Partners à ajouter
            partners_to_add = all_partners - current_partner_ids
            for partner in partners_to_add:
                self.env['discuss.channel.member'].create({
                    'channel_id': connection.channel_id.id,
                    'partner_id': partner.id,
                })
                _logger.info(f"✅ Added partner {partner.name} to channel {connection.channel_id.name}")

            # Partners à retirer (sauf le partner principal qui doit toujours rester)
            partners_to_remove = current_partner_ids - all_partners
            members_to_remove = current_members.filtered(
                lambda m: m.partner_id in partners_to_remove
            )
            if members_to_remove:
                members_to_remove.unlink()
                _logger.info(f"✅ Removed {len(members_to_remove)} partner(s) from channel {connection.channel_id.name}")

    @api.model
    def _find_or_create_channel(self, remote_instance_uuid):
        """
        Trouve ou crée un canal de discussion pour une connexion O'Chat
        Note: Cette méthode est maintenant obsolète car le canal est créé automatiquement
        lors de la création de la connexion. Gardée pour compatibilité.
        """
        # Chercher une connexion existante
        connection = self.search([('remote_instance_uuid', '=', remote_instance_uuid)], limit=1)

        if not connection:
            _logger.warning(f"⚠️ No connection found for instance {remote_instance_uuid}")
            return None

        # Le canal devrait déjà exister grâce à la méthode create()
        if connection.channel_id:
            return connection.channel_id

        # Fallback: créer le canal si inexistant (ne devrait pas arriver)
        _logger.warning(f"⚠️ Channel missing for connection {connection.name}, creating it now")
        channel = self.env['discuss.channel'].create({
            'name': f"{connection.name}",
            'description': f"Inter-instance communication with {connection.name}",
            'channel_type': 'ochat',
            'ochat_connection_id': connection.id,
        })

        connection.channel_id = channel.id
        _logger.info(f"✅ Created O'Chat channel for connection {connection.name}")

        return channel

    def action_send_test_message(self):
        """Envoie un message de test à l'instance distante"""
        self.ensure_one()

        # Récupérer la configuration O'Chat depuis les paramètres système
        ICP = self.env['ir.config_parameter'].sudo()

        instance_uuid = ICP.get_param('ochat.instance_uuid')
        instance_name = ICP.get_param('ochat.instance_name')
        central_server_url = ICP.get_param('ochat.central_server_url')
        api_key = ICP.get_param('ochat.api_key')
        is_registered = ICP.get_param('ochat.is_registered', 'False') == 'True'

        if not instance_name:
            raise UserError(_("Please configure O'Chat first (Settings > O'Chat)"))

        if not is_registered:
            raise UserError(_("Please register this instance with the central server first (Settings > O'Chat)"))

        if not api_key:
            raise UserError(_("Missing API key. Please re-register this instance."))

        # Préparer les données du message
        data = {
            'source_instance_uuid': instance_uuid,
            'target_instance_uuid': self.remote_instance_uuid,
            'content': f"🧪 Test message from {instance_name}!"
        }

        # Préparer les headers avec authentification
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        try:
            # Envoyer le message via le serveur central
            response = requests.post(
                f"{central_server_url}/api/v1/messages/send",
                json=data,
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                _logger.info(f"✅ Test message sent successfully to {self.name}")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Success'),
                        'message': _('Test message sent successfully!'),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                # Parser le JSON pour extraire le message détaillé
                error_message = f"Error {response.status_code}"
                try:
                    error_data = response.json()
                    if 'detail' in error_data:
                        error_message = error_data['detail']
                except:
                    error_message = response.text or error_message

                _logger.error(f"❌ Failed to send message: {response.status_code} - {response.text}")
                raise UserError(_("Failed to send message: %s", error_message))

        except requests.exceptions.RequestException as e:
            _logger.error(f"❌ Connection error: {str(e)}")
            raise UserError(f"Could not connect to central server: {str(e)}")
