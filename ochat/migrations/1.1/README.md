# O'Chat 1.1 Migration

## What does this migration do?

This migration updates existing `ochat.connection` records to work with the new connection request workflow system introduced in version 1.1.

### Changes Applied

1. **Status Update**: All existing connections are set to `status='accepted'`
   - Rationale: These connections were already working before the request system was implemented

2. **Direction Flag**: All existing connections are set to `is_incoming=False`
   - Rationale: These connections were manually created locally, not received from another instance

3. **Request Fields**: The fields `request_id`, `request_message`, and `rejection_reason` are left as NULL
   - Rationale: These connections didn't go through the request/acceptance workflow

## How to apply this migration

### Automatic (Recommended)

The migration will run automatically when you upgrade the O'Chat module from version 1.0 to 1.1:

```bash
# In Odoo CLI or via the web interface
./odoo-bin -u ochat -d your_database
```

Or via the Odoo web interface:
1. Go to Apps
2. Search for "O'Chat"
3. Click "Upgrade"

### Manual (If needed)

If you need to run the migration manually (e.g., if you're developing or testing):

```python
# In Odoo shell
env['ir.module.module'].search([('name', '=', 'ochat')]).button_immediate_upgrade()
```

Or via SQL (not recommended, but possible):

```sql
UPDATE ochat_connection
SET
    status = 'accepted',
    is_incoming = FALSE,
    updated_at = NOW() AT TIME ZONE 'UTC'
WHERE status IS NULL
   OR status NOT IN ('draft', 'pending', 'not_found', 'accepted', 'rejected');
```

## What if I don't have existing connections?

No problem! The migration will detect that there are no connections to migrate and will complete successfully without making any changes.

## Rollback

If you need to rollback (though this shouldn't be necessary), you can:

1. Downgrade the module to version 1.0
2. The new fields will still exist in the database but won't be used

Note: There's no need to rollback the data changes, as setting `status='accepted'` represents the true state of existing connections.
