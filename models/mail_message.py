# -*- coding: utf-8 -*-
"""
Extension du modèle mail.message pour supporter les statuts de livraison O'Chat
"""
from odoo import models, fields, api
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)


class MailMessage(models.Model):
    _inherit = 'mail.message'

    # Champs pour le suivi de livraison O'Chat
    ochat_fastapi_message_id = fields.Integer(
        string="FastAPI Message ID",
        help="ID du message dans le serveur FastAPI central",
        index=True,
        readonly=True  # Marquer comme readonly pour qu'ils soient toujours lus
    )

    ochat_delivery_status = fields.Selection([
        ('pending', 'En attente'),
        ('sent', 'Envoyé'),
        ('delivered', 'Délivré'),
        ('read', 'Lu'),
        ('retrying', 'En réessai'),
        ('failed', 'Échec')
    ], string="Statut de livraison O'Chat", default=False, readonly=True)

    ochat_retry_count = fields.Integer(
        string="Nombre de tentatives",
        default=0,
        help="Nombre de tentatives de livraison effectuées",
        readonly=True
    )

    ochat_failed_reason = fields.Char(
        string="Raison de l'échec",
        help="Message d'erreur si le message a échoué",
        readonly=True
    )

    ochat_delivered_at = fields.Datetime(
        string="Délivré le",
        help="Date et heure de livraison du message",
        readonly=True
    )

    ochat_read_at = fields.Datetime(
        string="Lu le",
        help="Date et heure de lecture du message par le destinataire",
        readonly=True
    )

    def _to_store(self, store, /, **kwargs):
        """
        Surcharge de _to_store pour ajouter les champs O'Chat au store
        """
        # Ajouter les champs O'Chat à la liste des champs à récupérer
        fields = kwargs.get('fields')
        if fields is None:
            # Utiliser les champs par défaut du parent
            super()._to_store(store, **kwargs)
        else:
            # Ajouter nos champs personnalisés à la liste
            ochat_fields = [
                'ochat_fastapi_message_id',
                'ochat_delivery_status',
                'ochat_retry_count',
                'ochat_failed_reason',
                'ochat_delivered_at',
                'ochat_read_at',
            ]
            # Créer une nouvelle liste avec tous les champs
            all_fields = list(fields) + ochat_fields
            kwargs['fields'] = all_fields
            super()._to_store(store, **kwargs)

        # Ajouter les champs O'Chat au store pour chaque message
        for message in self:
            data = {
                'ochat_fastapi_message_id': message.ochat_fastapi_message_id,
                'ochat_delivery_status': message.ochat_delivery_status,
                'ochat_retry_count': message.ochat_retry_count,
                'ochat_failed_reason': message.ochat_failed_reason,
                'ochat_delivered_at': message.ochat_delivered_at.isoformat() if message.ochat_delivered_at else False,
                'ochat_read_at': message.ochat_read_at.isoformat() if message.ochat_read_at else False,
            }
            store.add(message, data)

    def get_ochat_status_icon(self):
        """
        Retourne l'icône et la couleur à afficher selon le statut
        """
        self.ensure_one()

        if not self.ochat_delivery_status:
            return False

        status_map = {
            'pending': {'icon': 'fa-clock-o', 'color': 'text-muted', 'title': 'En attente'},
            'sent': {'icon': 'fa-check', 'color': 'text-muted', 'title': 'Envoyé'},
            'delivered': {'icon': 'fa-check-double', 'color': 'text-primary', 'title': 'Délivré'},
            'read': {'icon': 'fa-check-double', 'color': 'text-info', 'title': 'Lu'},
            'retrying': {'icon': 'fa-refresh', 'color': 'text-warning', 'title': f'En réessai (tentative {self.ochat_retry_count})'},
            'failed': {'icon': 'fa-times-circle', 'color': 'text-danger', 'title': 'Échec'}
        }

        return status_map.get(self.ochat_delivery_status, False)

    def _parse_iso_datetime(self, iso_datetime_str):
        """
        Parse une date ISO 8601 en datetime Python
        Gère les formats avec ou sans microsecondes
        """
        if not iso_datetime_str:
            return None

        try:
            # Essayer avec microsecondes
            if '.' in iso_datetime_str:
                return datetime.fromisoformat(iso_datetime_str.replace('Z', '+00:00'))
            else:
                return datetime.fromisoformat(iso_datetime_str.replace('Z', '+00:00'))
        except Exception as e:
            _logger.warning(f"Failed to parse datetime '{iso_datetime_str}': {e}")
            return None

    @api.model
    def update_ochat_status(self, fastapi_message_id, status, metadata=None):
        """
        Met à jour le statut de livraison d'un message O'Chat

        Args:
            fastapi_message_id: ID du message FastAPI
            status: Nouveau statut
            metadata: Métadonnées additionnelles (retry_count, error, etc.)
        """
        if metadata is None:
            metadata = {}

        message = self.search([
            ('ochat_fastapi_message_id', '=', fastapi_message_id)
        ], limit=1)

        if not message:
            _logger.warning(f"Message FastAPI {fastapi_message_id} not found in Odoo")
            return False

        vals = {'ochat_delivery_status': status}

        # Mettre à jour les champs selon le statut
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

        # Déclencher une notification pour mettre à jour l'interface
        # Récupérer le canal associé au message
        if message.model == 'discuss.channel' and message.res_id:
            channel = self.env['discuss.channel'].browse(message.res_id)
            if channel.exists():
                # Notifier via le bus les membres du canal
                try:
                    message_data = message.message_format()[0]
                    notifications = []
                    for member in channel.channel_member_ids:
                        notifications.append((
                            member.partner_id,
                            'mail.record/insert',
                            {'Message': [message_data]},
                        ))
                    self.env['bus.bus']._sendmany(notifications)
                except Exception as e:
                    _logger.warning(f"Could not send bus notification: {e}")

        _logger.info(f"✅ Updated message {message.id} status to '{status}'")

        return True
