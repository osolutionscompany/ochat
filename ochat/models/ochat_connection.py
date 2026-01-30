import requests
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class OchatConnection(models.Model):
    _name = 'ochat.connection'
    _description = "O'Chat Connection"
    _rec_name = 'name'

    partner_id = fields.Many2one(
        'res.partner',
        string='Contact',
        ondelete='cascade',
        copy=False
    )
    ochat_remote_name = fields.Char(string='Remote Instance Name', copy=False, help='Name of the remote instance')
    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
        readonly=True
    )
    remote_instance_uuid = fields.Char(string='Remote Instance UUID', copy=False)

    # Nouveaux champs pour le système de demande de connexion
    status = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('not_found', 'Instance Not Found'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected')
    ], string='Status', default='draft', required=True)
    request_id = fields.Integer(string='Request ID', readonly=True, help='Connection request ID on central server')
    request_message = fields.Text(string='Request Message', help='Optional message when sending connection request')
    rejection_reason = fields.Text(string='Rejection Reason', readonly=True, help='Reason for rejection if refused')
    is_incoming = fields.Boolean(string='Is Incoming', default=False, readonly=True,
                                 help='True if this is a received connection request')
    incoming_label = fields.Char(string='Type', compute='_compute_incoming_label', store=False)

    channel_id = fields.Many2one('discuss.channel', string='Discussion Channel')
    partner_ids = fields.Many2many(
        'res.partner',
        'ochat_connection_partner_rel',
        'connection_id',
        'partner_id',
        string='Additional Members',
        default=lambda self: [self.env.user.partner_id.id]
    )

    @api.depends('partner_id', 'partner_id.name', 'ochat_remote_name')
    def _compute_name(self):
        """Compute display name from partner or remote name"""
        for connection in self:
            if connection.partner_id:
                connection.name = connection.partner_id.name
            elif connection.ochat_remote_name:
                connection.name = connection.ochat_remote_name
            else:
                connection.name = _('New Connection')

    @api.constrains('remote_instance_uuid', 'partner_id', 'ochat_remote_name')
    def _check_required_fields(self):
        """Ensure remote_instance_uuid is filled and either partner_id or ochat_remote_name"""
        for connection in self:
            if not connection.remote_instance_uuid:
                raise ValidationError(_("Remote Instance UUID is required and cannot be empty."))
            if not connection.partner_id and not connection.ochat_remote_name:
                raise ValidationError(_("Either Contact or Remote Instance Name must be filled."))

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

    @api.depends('is_incoming')
    def _compute_incoming_label(self):
        """Compute label for incoming requests"""
        for connection in self:
            connection.incoming_label = 'New request' if connection.is_incoming and connection.status == 'pending' else ''

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to automatically create channel and sync members (only if accepted)"""
        connections = super().create(vals_list)

        for connection in connections:
            # Créer le canal O'Chat UNIQUEMENT si status='accepted'
            # Pour le nouveau workflow, le channel est créé après acceptation de la demande
            if connection.status == 'accepted' and not connection.channel_id:
                # Utiliser la méthode qui cherche d'abord un channel existant
                channel = connection._find_or_create_ochat_channel()
                connection.channel_id = channel.id

                # Synchroniser les partners (principal + additionnels)
                connection._sync_channel_members()

        return connections

    def write(self, vals):
        """Override write to sync channel members when partners change and create channel on acceptance"""
        res = super().write(vals)

        # Créer le channel si status passe à 'accepted'
        if 'status' in vals and vals['status'] == 'accepted':
            for connection in self:
                if not connection.channel_id:
                    # Utiliser la méthode qui cherche d'abord un channel existant
                    channel = connection._find_or_create_ochat_channel()
                    connection.channel_id = channel.id

                    # Synchroniser les partners
                    connection._sync_channel_members()

        # Re-sync si le partner principal ou les membres additionnels changent
        if 'partner_id' in vals or 'partner_ids' in vals:
            self._sync_channel_members()

        return res

    def _find_or_create_ochat_channel(self):
        """
        Trouve un channel existant pour ce remote_instance_uuid ou en crée un nouveau.
        Cela permet de réutiliser un channel si la connexion a été supprimée par erreur.
        """
        self.ensure_one()

        # Chercher un channel existant pour ce remote_instance_uuid
        # On utilise le champ ochat_remote_instance_uuid pour retrouver les channels orphelins
        existing_channel = self.env['discuss.channel'].search([
            ('channel_type', '=', 'ochat'),
            ('ochat_remote_instance_uuid', '=', self.remote_instance_uuid)
        ], limit=1)

        if existing_channel:
            _logger.info(
                f"♻️ Réutilisation du channel existant {existing_channel.name} (ID: {existing_channel.id}) pour {self.remote_instance_uuid}")
            # Reconnecter le channel à cette connexion si ce n'est pas déjà le cas
            if existing_channel.ochat_connection_id != self:
                existing_channel.ochat_connection_id = self.id
                _logger.info(f"🔗 Channel reconnecté à la connexion {self.name}")
            return existing_channel

        # Sinon, créer un nouveau channel
        channel = self.env['discuss.channel'].create({
            'name': f"{self.name}",
            'description': f"Inter-instance communication with {self.name}",
            'channel_type': 'ochat',
            'ochat_connection_id': self.id,
            'ochat_remote_instance_uuid': self.remote_instance_uuid,
        })
        _logger.info(f"✅ Création d'un nouveau channel O'Chat pour {self.name} (UUID: {self.remote_instance_uuid})")
        return channel

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
        # Utiliser la méthode qui cherche d'abord un channel existant
        channel = connection._find_or_create_ochat_channel()
        connection.channel_id = channel.id

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

    def action_send_request(self):
        """Envoyer une demande de connexion au serveur central"""
        self.ensure_one()

        if self.status not in ['draft', 'not_found']:
            raise UserError(_("Can only send request from draft or not_found status"))

        # Récupérer la configuration O'Chat
        ICP = self.env['ir.config_parameter'].sudo()
        instance_uuid = ICP.get_param('ochat.instance_uuid')
        central_server_url = ICP.get_param('ochat.central_server_url')
        api_key = ICP.get_param('ochat.api_key')
        is_registered = ICP.get_param('ochat.is_registered', 'False') == 'True'

        if not is_registered or not api_key:
            raise UserError(_("Please register this instance with the central server first (Settings > O'Chat)"))

        # Préparer les données de la demande
        data = {
            'source_uuid': instance_uuid,
            'target_uuid': self.remote_instance_uuid,
            'message': self.request_message or ''
        }

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        try:
            response = requests.post(
                f"{central_server_url}/api/v1/connections/request",
                json=data,
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                result = response.json()
                self.write({
                    'request_id': result['request_id'],
                    'status': result['status'],  # 'pending' ou 'not_found'
                    'is_incoming': False
                })
                _logger.info(f"✅ Connection request sent successfully to {self.remote_instance_uuid}")

                return {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                }
            else:
                error_message = f"Error {response.status_code}"
                try:
                    error_data = response.json()
                    if 'detail' in error_data:
                        error_message = error_data['detail']
                except:
                    error_message = response.text or error_message

                _logger.error(f"❌ Failed to send connection request: {response.status_code} - {response.text}")
                raise UserError(_("Failed to send request: %s", error_message))

        except requests.exceptions.RequestException as e:
            _logger.error(f"❌ Connection error: {str(e)}")
            raise UserError(f"Could not connect to central server: {str(e)}")

    def action_accept_request(self):
        """Accepter une demande de connexion reçue"""
        self.ensure_one()

        if self.status != 'pending' or not self.is_incoming:
            raise UserError(_("Can only accept pending incoming requests"))

        if not self.partner_id:
            raise UserError(_("You must select a contact before accepting the connection request."))

        # Récupérer la configuration O'Chat
        ICP = self.env['ir.config_parameter'].sudo()
        central_server_url = ICP.get_param('ochat.central_server_url')
        api_key = ICP.get_param('ochat.api_key')

        if not api_key:
            raise UserError(_("Missing API key. Please re-register this instance."))

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        try:
            response = requests.put(
                f"{central_server_url}/api/v1/connections/request/{self.request_id}/accept",
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                self.write({'status': 'accepted'})
                # Le channel sera créé automatiquement par write()
                _logger.info(f"✅ Connection request accepted: {self.name}")

                return {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                }
            else:
                error_message = f"Error {response.status_code}"
                try:
                    error_data = response.json()
                    if 'detail' in error_data:
                        error_message = error_data['detail']
                except:
                    error_message = response.text or error_message

                _logger.error(f"❌ Failed to accept request: {response.status_code} - {response.text}")
                raise UserError(_("Failed to accept: %s", error_message))

        except requests.exceptions.RequestException as e:
            _logger.error(f"❌ Connection error: {str(e)}")
            raise UserError(f"Could not connect to central server: {str(e)}")

    def action_reject_request(self):
        """Refuser une demande de connexion reçue"""
        self.ensure_one()

        if self.status != 'pending' or not self.is_incoming:
            raise UserError(_("Can only reject pending incoming requests"))

        # Récupérer la configuration O'Chat
        ICP = self.env['ir.config_parameter'].sudo()
        central_server_url = ICP.get_param('ochat.central_server_url')
        api_key = ICP.get_param('ochat.api_key')

        if not api_key:
            raise UserError(_("Missing API key. Please re-register this instance."))

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        # Ouvrir un wizard pour saisir la raison (optionnel pour l'instant, on met une raison par défaut)
        reason = "Connection request rejected"

        try:
            response = requests.put(
                f"{central_server_url}/api/v1/connections/request/{self.request_id}/reject",
                json={'reason': reason},
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                self.write({
                    'status': 'rejected',
                    'rejection_reason': reason
                })
                _logger.info(f"✅ Connection request rejected: {self.name}")

                return {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                }
            else:
                error_message = f"Error {response.status_code}"
                try:
                    error_data = response.json()
                    if 'detail' in error_data:
                        error_message = error_data['detail']
                except:
                    error_message = response.text or error_message

                _logger.error(f"❌ Failed to reject request: {response.status_code} - {response.text}")
                raise UserError(_("Failed to reject: %s", error_message))

        except requests.exceptions.RequestException as e:
            _logger.error(f"❌ Connection error: {str(e)}")
            raise UserError(f"Could not connect to central server: {str(e)}")

    def action_sync_connection_status(self):
        """Synchroniser le statut d'une connexion avec le serveur central"""
        self.ensure_one()

        if self.status not in ['pending', 'not_found']:
            raise UserError(_("Can only sync pending or not_found connections"))

        # Récupérer la configuration O'Chat
        ICP = self.env['ir.config_parameter'].sudo()
        central_server_url = ICP.get_param('ochat.central_server_url')
        api_key = ICP.get_param('ochat.api_key')

        if not api_key or not self.request_id:
            raise UserError(_("Missing API key or request ID"))

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        try:
            response = requests.get(
                f"{central_server_url}/api/v1/connections/request/{self.request_id}",
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                old_status = self.status
                self.write({
                    'status': data['status'],
                    'rejection_reason': data.get('rejection_reason', '')
                })
                # Le channel sera créé automatiquement par write() si status='accepted'

                if old_status != data['status']:
                    _logger.info(f"✅ Connection status updated: {old_status} → {data['status']}")
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'reload',
                    }
                else:
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Info'),
                            'message': _('Status unchanged: %s', data['status']),
                            'type': 'info',
                            'sticky': False,
                        }
                    }
            else:
                error_message = f"Error {response.status_code}"
                try:
                    error_data = response.json()
                    if 'detail' in error_data:
                        error_message = error_data['detail']
                except:
                    error_message = response.text or error_message

                _logger.error(f"❌ Failed to sync status: {response.status_code} - {response.text}")
                raise UserError(_("Failed to sync: %s", error_message))

        except requests.exceptions.RequestException as e:
            _logger.error(f"❌ Connection error: {str(e)}")
            raise UserError(f"Could not connect to central server: {str(e)}")

    @api.model
    def _cron_sync_connection_requests(self):
        """
        Cron job pour synchroniser automatiquement les demandes de connexion
        Tourne toutes les 5 minutes
        """
        _logger.info("🔄 Starting connection requests synchronization...")

        ICP = self.env['ir.config_parameter'].sudo()
        central_server_url = ICP.get_param('ochat.central_server_url')
        api_key = ICP.get_param('ochat.api_key')
        instance_uuid = ICP.get_param('ochat.instance_uuid')
        is_registered = ICP.get_param('ochat.is_registered', 'False') == 'True'

        if not is_registered or not api_key:
            _logger.warning("⚠️ Instance not registered, skipping sync")
            return

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        # PARTIE 1: Récupérer les demandes reçues (pending)
        try:
            response = requests.get(
                f"{central_server_url}/api/v1/connections/requests/received",
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                received_requests = response.json()

                for req in received_requests:
                    # Vérifier si on a déjà cette demande
                    existing = self.search([('request_id', '=', req['request_id'])], limit=1)

                    if not existing:
                        # NOUVELLE demande reçue, créer la connexion locale sans partner
                        self.create({
                            'ochat_remote_name': req['source_name'],
                            'remote_instance_uuid': req['source_uuid'],
                            'request_id': req['request_id'],
                            'status': 'pending',
                            'is_incoming': True,
                            'request_message': req.get('request_message', ''),
                        })
                        _logger.info(f"✅ New incoming connection request from {req['source_name']}")

        except requests.exceptions.RequestException as e:
            _logger.error(f"❌ Error fetching received requests: {str(e)}")

        # PARTIE 2: Synchroniser les demandes envoyées (vérifier status updates)
        pending_connections = self.search([
            ('status', 'in', ['pending', 'not_found']),
            ('is_incoming', '=', False),
            ('request_id', '!=', False)
        ])

        for conn in pending_connections:
            try:
                response = requests.get(
                    f"{central_server_url}/api/v1/connections/request/{conn.request_id}",
                    headers=headers,
                    timeout=10
                )

                if response.status_code == 200:
                    data = response.json()

                    if data['status'] != conn.status:
                        _logger.info(f"📝 Updating connection {conn.id}: {conn.status} → {data['status']}")

                        conn.write({
                            'status': data['status'],
                            'rejection_reason': data.get('rejection_reason', '')
                        })
                        # Le channel sera créé automatiquement par write() si status='accepted'

            except requests.exceptions.RequestException as e:
                _logger.error(f"❌ Error syncing connection {conn.id}: {str(e)}")

        _logger.info("✅ Connection requests synchronization completed")
