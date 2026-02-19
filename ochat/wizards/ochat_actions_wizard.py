# -*- coding: utf-8 -*-
"""
Wizard for O'Chat administrative actions
"""
import requests
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OchatActionsWizard(models.TransientModel):
    _name = 'ochat.actions.wizard'
    _description = "O'Chat Actions Wizard"

    action_type = fields.Selection([
        ('sync_all', 'Sync All Connections'),
        ('sync_pending', 'Sync Pending Requests Only')
    ], string='Action', required=True, default='sync_pending',
       help='Choose the synchronization action to perform')

    action_description = fields.Html(
        string='Description',
        compute='_compute_action_description',
        store=False
    )

    result_message = fields.Html(
        string='Result',
        readonly=True,
        help='Result of the last action execution'
    )

    @api.depends('action_type')
    def _compute_action_description(self):
        """Display helpful description based on selected action"""
        for wizard in self:
            if wizard.action_type == 'sync_all':
                wizard.action_description = _(
                    "<p><strong>Sync All Connections</strong></p>"
                    "<p>This action will:</p>"
                    "<ul>"
                    "<li>Fetch ALL connection requests from the central server (sent and received)</li>"
                    "<li>Include all statuses: pending, accepted, rejected, not_found</li>"
                    "<li>Create new connections or update existing ones</li>"
                    "<li>Automatically create discussion channels for accepted connections</li>"
                    "</ul>"
                    "<p><em>Use this for a complete synchronization.</em></p>"
                )
            elif wizard.action_type == 'sync_pending':
                wizard.action_description = _(
                    "<p><strong>Sync Pending Requests Only</strong></p>"
                    "<p>This action will:</p>"
                    "<ul>"
                    "<li>Fetch only PENDING incoming connection requests</li>"
                    "<li>Create new pending requests that aren't in your system yet</li>"
                    "<li>Sync status updates for existing sent requests</li>"
                    "</ul>"
                    "<p><em>This is the same action that runs automatically every 5 minutes.</em></p>"
                )
            else:
                wizard.action_description = _("<p>Please select an action.</p>")

    def _get_ochat_config(self):
        """Helper method to retrieve O'Chat configuration"""
        ICP = self.env['ir.config_parameter'].sudo()
        return {
            'central_server_url': ICP.get_param('ochat.central_server_url'),
            'api_key': ICP.get_param('ochat.api_key'),
            'instance_uuid': ICP.get_param('ochat.instance_uuid'),
            'is_registered': ICP.get_param('ochat.is_registered', 'False') == 'True'
        }

    def _validate_configuration(self, config):
        """Validate that O'Chat is properly configured"""
        if not config['is_registered'] or not config['api_key']:
            raise UserError(_("Instance not registered. Please register first in O'Chat Settings."))

        if not config['central_server_url']:
            raise UserError(_("Central server URL not configured. Please configure in O'Chat Settings."))

    def _get_auth_headers(self, api_key):
        """Get authorization headers for API calls"""
        return {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

    def _sync_pending_requests_logic(self, config):
        """
        Core logic for syncing pending requests.
        Extracted from _cron_sync_connection_requests to enable reuse.
        Returns: dict with statistics
        """
        headers = self._get_auth_headers(config['api_key'])
        stats = {
            'new_incoming': 0,
            'updated_sent': 0,
            'errors': []
        }

        # PART 1: Fetch received pending requests
        try:
            response = requests.get(
                f"{config['central_server_url']}/api/v1/connections/requests/received",
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                response_data = response.json()
                # L'API retourne un format paginé {"items": [...], "total": ...}
                received_requests = response_data.get('items', response_data) if isinstance(response_data, dict) else response_data

                for req in received_requests:
                    # Check if we already have this request by request_id
                    existing = self.env['ochat.connection'].search([
                        ('request_id', '=', req['request_id'])
                    ], limit=1)

                    # If not found by request_id, check by remote_instance_uuid
                    if not existing:
                        existing = self.env['ochat.connection'].search([
                            ('remote_instance_uuid', '=', req['source_uuid'])
                        ], limit=1)

                    if existing:
                        # Update existing connection with the new request data
                        existing.write({
                            'request_id': req['request_id'],
                            'status': 'pending',
                            'is_incoming': True,
                            'request_message': req.get('request_message', ''),
                            'ochat_remote_name': req['source_name'],
                        })
                        stats['new_incoming'] += 1
                        _logger.info(f"📝 Updated existing connection with incoming request from {req['source_name']}")
                    else:
                        # NEW incoming request, create local connection
                        self.env['ochat.connection'].create({
                            'ochat_remote_name': req['source_name'],
                            'remote_instance_uuid': req['source_uuid'],
                            'request_id': req['request_id'],
                            'status': 'pending',
                            'is_incoming': True,
                            'request_message': req.get('request_message', ''),
                        })
                        stats['new_incoming'] += 1
                        _logger.info(f"✅ New incoming connection request from {req['source_name']}")
            else:
                stats['errors'].append(f"Failed to fetch received requests: HTTP {response.status_code}")

        except requests.exceptions.RequestException as e:
            stats['errors'].append(f"Error fetching received requests: {str(e)}")
            _logger.error(f"❌ Error fetching received requests: {str(e)}")

        # PART 2: Sync sent requests (check for status updates)
        pending_connections = self.env['ochat.connection'].search([
            ('status', 'in', ['pending', 'not_found']),
            ('is_incoming', '=', False),
            ('request_id', '!=', False)
        ])

        for conn in pending_connections:
            try:
                response = requests.get(
                    f"{config['central_server_url']}/api/v1/connections/request/{conn.request_id}",
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
                        stats['updated_sent'] += 1
                        # Channel will be created automatically by write() if status='accepted'
                else:
                    stats['errors'].append(f"Failed to sync connection {conn.id}: HTTP {response.status_code}")

            except requests.exceptions.RequestException as e:
                stats['errors'].append(f"Error syncing connection {conn.id}: {str(e)}")
                _logger.error(f"❌ Error syncing connection {conn.id}: {str(e)}")

        return stats

    def _sync_all_connections_logic(self, config):
        """
        Logic for syncing all connections from central server.
        Returns: dict with statistics
        """
        headers = self._get_auth_headers(config['api_key'])
        stats = {
            'created': 0,
            'updated': 0,
            'errors': []
        }

        try:
            response = requests.get(
                f"{config['central_server_url']}/api/v1/connections/all",
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                response_data = response.json()
                # L'API retourne un format paginé {"items": [...], "total": ...}
                all_connections = response_data.get('items', response_data) if isinstance(response_data, dict) else response_data
                _logger.info(f"📥 Fetched {len(all_connections)} connections from server")

                for conn_data in all_connections:
                    # Determine if this is an incoming or outgoing connection
                    is_incoming = conn_data['target_uuid'] == config['instance_uuid']
                    remote_uuid = conn_data['source_uuid'] if is_incoming else conn_data['target_uuid']

                    # Check if connection already exists by request_id
                    existing = self.env['ochat.connection'].search([
                        ('request_id', '=', conn_data['request_id'])
                    ], limit=1)

                    # If not found by request_id, check by remote_instance_uuid
                    # This handles the case where a connection was created manually or from another sync
                    if not existing:
                        existing = self.env['ochat.connection'].search([
                            ('remote_instance_uuid', '=', remote_uuid)
                        ], limit=1)

                    if existing:
                        # Update existing connection (sync the server data)
                        update_vals = {
                            'request_id': conn_data['request_id'],  # Update request_id if it was found by UUID
                            'status': conn_data['status'],
                            'rejection_reason': conn_data.get('rejection_reason', ''),
                            'request_message': conn_data.get('request_message', ''),
                            'is_incoming': is_incoming,  # Update direction in case it changed
                        }

                        # Update remote name if incoming and not set
                        if is_incoming and not existing.ochat_remote_name:
                            update_vals['ochat_remote_name'] = conn_data['source_name']
                        elif not is_incoming:
                            update_vals['ochat_remote_name'] = conn_data['target_name']

                        existing.write(update_vals)
                        stats['updated'] += 1
                        _logger.info(f"📝 Updated connection {existing.id}: {conn_data['source_name']} ↔ {conn_data['target_name']}")
                    else:
                        # Create new connection
                        create_vals = {
                            'request_id': conn_data['request_id'],
                            'remote_instance_uuid': remote_uuid,
                            'status': conn_data['status'],
                            'is_incoming': is_incoming,
                            'request_message': conn_data.get('request_message', ''),
                            'rejection_reason': conn_data.get('rejection_reason', ''),
                            'ochat_remote_name': conn_data['source_name'] if is_incoming else conn_data['target_name'],
                            'channel_id': False,
                        }

                        self.env['ochat.connection'].create(create_vals)
                        stats['created'] += 1
                        _logger.info(f"✅ Created connection: {conn_data['source_name']} ↔ {conn_data['target_name']} (status: {conn_data['status']})")
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get('detail', error_msg)
                except (ValueError, KeyError):
                    pass
                stats['errors'].append(f"Failed to fetch connections: {error_msg}")
                _logger.error(f"❌ Failed to fetch all connections: {response.status_code}")

        except requests.exceptions.RequestException as e:
            stats['errors'].append(f"Connection error: {str(e)}")
            _logger.error(f"❌ Error fetching all connections: {str(e)}")

        return stats

    def action_execute(self):
        """Execute the selected action"""
        self.ensure_one()

        # Get and validate configuration
        config = self._get_ochat_config()
        self._validate_configuration(config)

        # Execute action based on selection
        if self.action_type == 'sync_all':
            _logger.info("🔄 Starting manual sync: ALL connections")
            stats = self._sync_all_connections_logic(config)

            # Build result message
            result_parts = []
            result_parts.append(f"<p><strong>Sync All Connections - Completed</strong></p>")
            result_parts.append(f"<ul>")
            result_parts.append(f"<li><strong>{stats['created']}</strong> connection(s) created</li>")
            result_parts.append(f"<li><strong>{stats['updated']}</strong> connection(s) updated</li>")

            if stats['errors']:
                result_parts.append(f"<li><strong style='color: #d32f2f;'>{len(stats['errors'])}</strong> error(s) occurred</li>")
                result_parts.append("</ul>")
                result_parts.append("<p><strong>Errors:</strong></p><ul>")
                for error in stats['errors'][:5]:  # Limit to first 5 errors
                    result_parts.append(f"<li style='color: #d32f2f;'>{error}</li>")
                if len(stats['errors']) > 5:
                    result_parts.append(f"<li><em>... and {len(stats['errors']) - 5} more</em></li>")
            result_parts.append("</ul>")

            self.result_message = ''.join(result_parts)

            # Show notification
            notification_type = 'warning' if stats['errors'] else 'success'
            notification_message = _('Synchronized %d new and %d updated connections', stats['created'], stats['updated'])
            if stats['errors']:
                notification_message += _(' (%d errors)', len(stats['errors']))

        elif self.action_type == 'sync_pending':
            _logger.info("🔄 Starting manual sync: PENDING requests")
            stats = self._sync_pending_requests_logic(config)

            # Build result message
            result_parts = []
            result_parts.append(f"<p><strong>Sync Pending Requests - Completed</strong></p>")
            result_parts.append(f"<ul>")
            result_parts.append(f"<li><strong>{stats['new_incoming']}</strong> new incoming request(s)</li>")
            result_parts.append(f"<li><strong>{stats['updated_sent']}</strong> sent request(s) updated</li>")

            if stats['errors']:
                result_parts.append(f"<li><strong style='color: #d32f2f;'>{len(stats['errors'])}</strong> error(s) occurred</li>")
                result_parts.append("</ul>")
                result_parts.append("<p><strong>Errors:</strong></p><ul>")
                for error in stats['errors'][:5]:
                    result_parts.append(f"<li style='color: #d32f2f;'>{error}</li>")
                if len(stats['errors']) > 5:
                    result_parts.append(f"<li><em>... and {len(stats['errors']) - 5} more</em></li>")
            result_parts.append("</ul>")

            self.result_message = ''.join(result_parts)

            # Show notification
            notification_type = 'warning' if stats['errors'] else 'success'
            notification_message = _('Synchronized %d new and %d updated requests', stats['new_incoming'], stats['updated_sent'])
            if stats['errors']:
                notification_message += _(' (%d errors)', len(stats['errors']))

        else:
            raise UserError(_("Please select an action"))

        # Return action to reload the wizard form and show notification
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'ochat.actions.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {
                **self.env.context,
                'notification_info': {
                    'type': notification_type,
                    'title': _('Synchronization Complete'),
                    'message': notification_message,
                    'sticky': False,
                }
            }
        }
