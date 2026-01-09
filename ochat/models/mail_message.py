# -*- coding: utf-8 -*-
"""
Extension of mail.message model to support O'Chat delivery status tracking
"""
from odoo import models, fields, api
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)


class MailMessage(models.Model):
    _inherit = 'mail.message'

    # O'Chat delivery tracking fields
    ochat_fastapi_message_id = fields.Integer(
        string="FastAPI Message ID",
        help="Message ID in the central FastAPI server",
        index=True,
        readonly=True
    )

    ochat_delivery_status = fields.Selection([
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('read', 'Read'),
        ('retrying', 'Retrying'),
        ('failed', 'Failed')
    ], string="O'Chat Delivery Status", default=False, readonly=True)

    ochat_retry_count = fields.Integer(
        string="Retry Count",
        default=0,
        help="Number of delivery attempts made",
        readonly=True
    )

    ochat_failed_reason = fields.Char(
        string="Failure Reason",
        help="Error message if the message failed",
        readonly=True
    )

    ochat_delivered_at = fields.Datetime(
        string="Delivered At",
        help="Date and time when the message was delivered",
        readonly=True
    )

    ochat_read_at = fields.Datetime(
        string="Read At",
        help="Date and time when the message was read by the recipient",
        readonly=True
    )

    def write(self, vals):
        """
        Override write to send bus notification when O'Chat status changes
        """
        # Check if any O'Chat field is being updated
        ochat_fields_updated = any(
            field in vals
            for field in ['ochat_delivery_status', 'ochat_fastapi_message_id', 'ochat_retry_count',
                         'ochat_failed_reason', 'ochat_delivered_at', 'ochat_read_at']
        )

        result = super().write(vals)

        # Send bus notification if O'Chat fields changed
        if ochat_fields_updated:
            for message in self:
                if message.model == 'discuss.channel' and message.res_id:
                    channel = self.env['discuss.channel'].browse(message.res_id)
                    if channel.exists() and channel.channel_type == 'ochat':
                        try:
                            from odoo.addons.mail.tools.discuss import Store

                            # Send notification to all channel members
                            # V19: Use Store with bus_channel and call bus_send()
                            for member in channel.channel_member_ids:
                                if member.partner_id and member.partner_id.main_user_id:
                                    user = member.partner_id.main_user_id
                                    store = Store(bus_channel=user)
                                    # Pass empty list instead of None to avoid issues with rating module
                                    message.with_user(user)._to_store(store, fields=[])
                                    store.bus_send()

                        except Exception as e:
                            _logger.warning(f"Could not send O'Chat status update notification: {e}")

        return result

    def _to_store(self, store, /, fields=None, **kwargs):
        """
        Override _to_store to add O'Chat fields to the store
        V19: Call parent first, then add our fields using add_model_values
        """
        # Call parent first to handle the base fields
        super()._to_store(store, fields=fields, **kwargs)

        # Add O'Chat fields to the store using add_model_values
        # Loop through each message in case self is a recordset
        for message in self:
            if message.ochat_delivery_status:
                store.add_model_values('mail.message', {
                    'id': message.id,
                    'ochat_fastapi_message_id': message.ochat_fastapi_message_id,
                    'ochat_delivery_status': message.ochat_delivery_status,
                    'ochat_retry_count': message.ochat_retry_count,
                    'ochat_failed_reason': message.ochat_failed_reason,
                    'ochat_delivered_at': message.ochat_delivered_at,
                    'ochat_read_at': message.ochat_read_at,
                })

    def get_ochat_status_icon(self):
        """
        Returns the icon and color to display based on the status
        """
        self.ensure_one()

        if not self.ochat_delivery_status:
            return False

        status_map = {
            'pending': {'icon': 'fa-clock-o', 'color': 'text-muted', 'title': 'Pending'},
            'sent': {'icon': 'fa-check', 'color': 'text-muted', 'title': 'Sent'},
            'delivered': {'icon': 'fa-check-double', 'color': 'text-primary', 'title': 'Delivered'},
            'read': {'icon': 'fa-check-double', 'color': 'text-info', 'title': 'Read'},
            'retrying': {'icon': 'fa-refresh', 'color': 'text-warning', 'title': f'Retrying (attempt {self.ochat_retry_count})'},
            'failed': {'icon': 'fa-times-circle', 'color': 'text-danger', 'title': 'Failed'}
        }

        return status_map.get(self.ochat_delivery_status, False)

    def _parse_iso_datetime(self, iso_datetime_str):
        """
        Parse an ISO 8601 date string to a naive Python datetime
        Odoo always expects naive datetimes in UTC
        """
        if not iso_datetime_str:
            return None

        try:
            # Parse the datetime with timezone
            dt = datetime.fromisoformat(iso_datetime_str.replace('Z', '+00:00'))

            # Convert to UTC if needed and remove timezone (make naive)
            if dt.tzinfo is not None:
                from datetime import timezone
                dt_utc = dt.astimezone(timezone.utc)
                return dt_utc.replace(tzinfo=None)

            return dt
        except Exception as e:
            _logger.warning(f"Failed to parse datetime '{iso_datetime_str}': {e}")
            return None

    @api.model
    def update_ochat_status(self, fastapi_message_id, status, metadata=None):
        """
        Update the delivery status of an O'Chat message

        Args:
            fastapi_message_id: FastAPI message ID
            status: New status
            metadata: Additional metadata (retry_count, error, etc.)
        """
        if metadata is None:
            metadata = {}

        message = self.search([
            ('ochat_fastapi_message_id', '=', fastapi_message_id)
        ], limit=1)

        if not message:
            _logger.warning(f"O'Chat message {fastapi_message_id} not found")
            return False

        vals = {'ochat_delivery_status': status}

        # Update fields based on status
        if status == 'retrying':
            vals['ochat_retry_count'] = metadata.get('retry_count', 0)

        elif status == 'delivered':
            vals['ochat_retry_count'] = metadata.get('retry_count', 0)
            if metadata.get('delivered_at'):
                delivered_at = self._parse_iso_datetime(metadata['delivered_at'])
                if delivered_at:
                    vals['ochat_delivered_at'] = delivered_at

        elif status == 'read':
            if metadata.get('read_at'):
                read_at = self._parse_iso_datetime(metadata['read_at'])
                if read_at:
                    vals['ochat_read_at'] = read_at

        elif status == 'failed':
            vals['ochat_retry_count'] = metadata.get('retry_count', 0)
            vals['ochat_failed_reason'] = metadata.get('error', 'Unknown error')

        # write() will automatically trigger bus notification via our override
        message.write(vals)
        return True
