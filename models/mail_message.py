# -*- coding: utf-8 -*-
"""
Extension du modèle mail.message pour supporter les statuts de livraison O'Chat
"""
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class MailMessage(models.Model):
    _inherit = 'mail.message'

    # Champs pour le suivi de livraison O'Chat
    ochat_fastapi_message_id = fields.Integer(
        string="FastAPI Message ID",
        help="ID du message dans le serveur FastAPI central",
        index=True
    )

    ochat_delivery_status = fields.Selection([
        ('pending', 'En attente'),
        ('sent', 'Envoyé'),
        ('delivered', 'Délivré'),
        ('read', 'Lu'),
        ('retrying', 'En réessai'),
        ('failed', 'Échec')
    ], string="Statut de livraison O'Chat", default=False)

    ochat_retry_count = fields.Integer(
        string="Nombre de tentatives",
        default=0,
        help="Nombre de tentatives de livraison effectuées"
    )

    ochat_failed_reason = fields.Char(
        string="Raison de l'échec",
        help="Message d'erreur si le message a échoué"
    )

    ochat_delivered_at = fields.Datetime(
        string="Délivré le",
        help="Date et heure de livraison du message"
    )

    ochat_read_at = fields.Datetime(
        string="Lu le",
        help="Date et heure de lecture du message par le destinataire"
    )

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
                vals['ochat_delivered_at'] = metadata['delivered_at']

        elif status == 'read':
            if metadata.get('read_at'):
                vals['ochat_read_at'] = metadata['read_at']

        elif status == 'failed':
            vals['ochat_retry_count'] = metadata.get('retry_count', 0)
            vals['ochat_failed_reason'] = metadata.get('error', 'Unknown error')

        message.write(vals)
        _logger.info(f"✅ Updated message {message.id} status to '{status}'")

        return True
