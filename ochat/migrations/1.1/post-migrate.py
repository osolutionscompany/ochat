# -*- coding: utf-8 -*-
"""
Migration script pour O'Chat version 1.1
Met à jour les connexions existantes pour le nouveau système de demande de connexion
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """
    Migration des connexions existantes

    Cette migration:
    - Met toutes les connexions existantes à status='accepted'
      (elles fonctionnaient déjà avant le système de demande)
    - Met is_incoming=False pour toutes les connexions existantes
      (elles ont été créées manuellement localement)
    - Laisse request_id, request_message et rejection_reason à NULL
    """
    _logger.info("🔄 Starting O'Chat 1.1 migration: updating existing connections...")

    # Compter le nombre de connexions à migrer
    cr.execute("""
        SELECT COUNT(*)
        FROM ochat_connection
        WHERE status IS NULL OR status NOT IN ('draft', 'pending', 'not_found', 'accepted', 'rejected')
    """)
    count = cr.fetchone()[0]

    if count == 0:
        _logger.info("✅ No connections to migrate")
        return

    _logger.info(f"📊 Found {count} connections to migrate")

    # Mettre à jour toutes les connexions existantes
    cr.execute("""
        UPDATE ochat_connection
        SET
            status = 'accepted',
            is_incoming = FALSE,
            updated_at = NOW() AT TIME ZONE 'UTC'
        WHERE status IS NULL
           OR status NOT IN ('draft', 'pending', 'not_found', 'accepted', 'rejected')
    """)

    _logger.info(f"✅ Successfully migrated {count} connections to status='accepted'")
    _logger.info("✅ O'Chat 1.1 migration completed")
