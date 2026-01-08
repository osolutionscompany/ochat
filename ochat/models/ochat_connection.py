import requests
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


# TODO:
# 1. The channel should be automatically created when creating the connection so we can also add partners directly to it
# 2. The message should POP on the partners screen when received
# 3. Need to implement the reply part now
# 4. I think we should create a channel type O'Chat to not break the inheritance and base it on how messages are received and sent in the whatsapp module

class OchatConnection(models.Model):
    _name = 'ochat.connection'
    _description = "O'Chat Connection"
    _rec_name = 'partner_id'

    partner_id = fields.Many2one(
        'res.partner',
        string='Contact',
        required=True,
        ondelete='cascade'
    )
    name = fields.Char(
        string='Name',
        related='partner_id.name',
        store=True,
        readonly=True
    )
    remote_instance_uuid = fields.Char(string='Remote Instance UUID', required=True)
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
        string='Additional Members'
    )

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
            # Automatically create the O'Chat channel
            if not connection.channel_id:
                channel = self.env['discuss.channel'].create({
                    'name': f"{connection.name}",
                    'description': f"Inter-instance communication with {connection.name}",
                    'channel_type': 'ochat',
                    'ochat_connection_id': connection.id,
                })
                connection.channel_id = channel.id
                _logger.info(f"✅ Auto-created O'Chat channel for new connection {connection.name}")

            # Synchronize partners (main + additional)
            connection._sync_channel_members()

        return connections

    def write(self, vals):
        """Override write to sync channel members when partners change"""
        res = super().write(vals)

        # Re-sync if main partner or additional members change
        if 'partner_id' in vals or 'partner_ids' in vals:
            self._sync_channel_members()

        return res

    def _sync_channel_members(self):
        """Synchronize discuss.channel.member with partner_id + partner_ids"""
        for connection in self:
            if not connection.channel_id:
                continue

            # All partners to include: main + additional
            all_partners = connection.partner_id | connection.partner_ids

            # Get current channel members
            current_members = connection.channel_id.channel_member_ids
            current_partner_ids = current_members.mapped('partner_id')

            # Partners to add
            partners_to_add = all_partners - current_partner_ids
            for partner in partners_to_add:
                self.env['discuss.channel.member'].create({
                    'channel_id': connection.channel_id.id,
                    'partner_id': partner.id,
                })
                _logger.info(f"✅ Added partner {partner.name} to channel {connection.channel_id.name}")

            # Partners to remove (except main partner who must always stay)
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
        Find or create a discussion channel for an O'Chat connection
        Note: This method is now deprecated because the channel is created automatically
        when the connection is created. Kept for backward compatibility.
        """
        # Search for existing connection
        connection = self.search([('remote_instance_uuid', '=', remote_instance_uuid)], limit=1)

        if not connection:
            _logger.warning(f"⚠️ No connection found for instance {remote_instance_uuid}")
            return None

        # The channel should already exist thanks to the create() method
        if connection.channel_id:
            return connection.channel_id

        # Fallback: create channel if missing (should not happen)
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
        """Send a test message to the remote instance"""
        self.ensure_one()

        # Retrieve O'Chat configuration from system parameters
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

        # Prepare message data
        data = {
            'source_instance_uuid': instance_uuid,
            'target_instance_uuid': self.remote_instance_uuid,
            'content': f"🧪 Test message from {instance_name}!"
        }

        # Prepare headers with authentication
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        try:
            # Send message via central server
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
                _logger.error(f"❌ Failed to send message: {response.status_code} - {response.text}")
                raise UserError(f"Failed to send message: {response.status_code}")

        except requests.exceptions.RequestException as e:
            _logger.error(f"❌ Connection error: {str(e)}")
            raise UserError(f"Could not connect to central server: {str(e)}")
