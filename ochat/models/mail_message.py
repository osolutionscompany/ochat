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

    def _message_format_extras(self, format_reply):
        """
        Override _message_format_extras to add O'Chat fields to message format
        This method is called by _message_format to add custom fields to messages
        """
        vals = super()._message_format_extras(format_reply)

        # Add O'Chat fields to the message data
        vals.update({
            'ochat_fastapi_message_id': self.ochat_fastapi_message_id,
            'ochat_delivery_status': self.ochat_delivery_status,
            'ochat_retry_count': self.ochat_retry_count,
            'ochat_failed_reason': self.ochat_failed_reason,
            'ochat_delivered_at': self.ochat_delivered_at.isoformat() if self.ochat_delivered_at else False,
            'ochat_read_at': self.ochat_read_at.isoformat() if self.ochat_read_at else False,
        })

        return vals

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
            _logger.warning(f"FastAPI message {fastapi_message_id} not found in Odoo")
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

        message.write(vals)

        # Force commit to ensure data is in DB
        self.env.cr.commit()

        # Trigger real-time interface update via bus notification
        if message.model == 'discuss.channel' and message.res_id:
            channel = self.env['discuss.channel'].browse(message.res_id)
            if channel.exists():
                try:
                    # Get complete formatted message with updated O'Chat fields
                    formatted_messages = message.message_format()
                    if formatted_messages:
                        # Send complete message update to all channel members
                        notifications = []
                        for member in channel.channel_member_ids:
                            if member.partner_id:
                                notifications.append([
                                    member.partner_id,
                                    'mail.record/insert',
                                    {'Message': [formatted_messages[0]]}
                                ])

                        if notifications:
                            self.env['bus.bus']._sendmany(notifications)
                            _logger.info(f"✅ Sent status update notification for message {message.id}: {status}")

                except Exception as e:
                    _logger.warning(f"Could not send bus notification: {e}")

        return True
