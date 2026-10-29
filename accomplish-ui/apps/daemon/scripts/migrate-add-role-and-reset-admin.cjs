'use strict';
require('dotenv').config({ path: require('path').join(__dirname, '../.env') });
const { Client } = require('pg');
const bcrypt = require('bcryptjs');

// One-off migration for an already-running database whose `users` table
// predates the `role` column, and whose seeded admin row was created by an
// earlier version of init-db.cjs's `ON CONFLICT DO NOTHING` seed (which
// silently no-ops on a DB that already has an `admin` row, so it never picks
// up a changed seed password/role on its own). Safe to re-run.
async function main() {
  const client = new Client({
    host: process.env.PG_HOST?.trim(),
    port: Number(process.env.PG_PORT ?? 5432),
    database: process.env.PG_DB?.trim(),
    user: process.env.PG_USER?.trim(),
    password: process.env.PG_PASSWORD?.trim(),
  });

  console.log(`[migrate-roles] Connecting to ${process.env.PG_HOST?.trim()}:${process.env.PG_PORT ?? 5432}/${process.env.PG_DB?.trim()}...`);
  await client.connect();
  console.log('[migrate-roles] Connected.');

  await client.query(
    `ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'user'`,
  );
  console.log('[migrate-roles] role column present.');

  const hash = bcrypt.hashSync('admin', 10);
  const result = await client.query(
    `UPDATE users
     SET role = 'admin', password_hash = $1, updated_at = NOW()
     WHERE uid = 'admin'
     RETURNING id, uid, role`,
    [hash],
  );

  if (result.rowCount > 0) {
    console.log(`[migrate-roles] Updated admin@... role=admin, password reset. (id=${result.rows[0].id})`);
  } else {
    console.log('[migrate-roles] No user with uid=\'admin\' found -- nothing to update.');
  }

  console.log('\n✅ Migration complete.\n');
  await client.end();
}

main().catch((e) => {
  console.error('[migrate-roles] Failed:', e.message);
  process.exit(1);
});
