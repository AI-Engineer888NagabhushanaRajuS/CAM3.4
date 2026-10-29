import { Pool } from 'pg';
import bcrypt from 'bcryptjs';
import { log } from '../logger.js';

let pool: Pool | null = null;

export function getPool(): Pool {
  if (!pool) {
    pool = new Pool({
      host: process.env.PG_HOST ?? 'localhost',
      port: Number(process.env.PG_PORT ?? 5432),
      database: process.env.PG_DB ?? 'srim',
      user: process.env.PG_USER ?? 'postgres',
      password: process.env.PG_PASSWORD,
      max: 5,
      idleTimeoutMillis: 30_000,
      connectionTimeoutMillis: 5_000,
    });
    pool.on('error', (err: Error) => {
      log.warn(`[PgAuth] Pool error: ${err.message}`);
    });
  }
  return pool;
}

export type UserRole = 'admin' | 'user' | 'fde';

export interface PgUser {
  id: string;
  name: string;
  email: string;
  role: UserRole;
}

type DbRow = {
  id: number;
  uid?: string;
  full_name?: string;
  email: string;
  password_hash: string;
  is_active?: boolean;
  role?: string;
};

function toRole(value: string | undefined): UserRole {
  if (value === 'admin' || value === 'fde') return value;
  return 'user';
}

async function verifyRow(row: DbRow | undefined, password: string): Promise<PgUser | null> {
  if (!row) return null;
  const valid = await bcrypt.compare(password, row.password_hash);
  if (!valid) return null;
  if (row.is_active === false) { throw new Error('Account inactive or disabled'); }
  return {
    id: String(row.id),
    name: row.full_name ?? row.uid ?? row.email,
    email: row.email,
    role: toRole(row.role),
  };
}

export async function pgLoginByUid(uid: string, password: string): Promise<PgUser | null> {
  const result = await getPool().query<DbRow>(
    'SELECT id, uid, full_name, email, password_hash, is_active, role FROM users WHERE uid = $1 LIMIT 1',
    [uid],
  );
  return verifyRow(result.rows[0], password);
}

export async function pgLoginByEmail(email: string, password: string): Promise<PgUser | null> {
  const result = await getPool().query<DbRow>(
    'SELECT id, uid, full_name, email, password_hash, is_active, role FROM users WHERE email = $1 LIMIT 1',
    [email.toLowerCase()],
  );
  return verifyRow(result.rows[0], password);
}

/**
 * Auto-detects whether `identifier` is an email (contains @) or a UID and
 * queries the appropriate column. Returns null if not found or wrong password.
 */
export async function pgLogin(identifier: string, password: string): Promise<PgUser | null> {
  if (!process.env.PG_HOST && !process.env.PG_DB) {
    log.warn('[PgAuth] PostgreSQL not configured (PG_HOST/PG_DB missing) — skipping pg auth');
    return null;
  }
  const isEmail = identifier.includes('@');
  return isEmail ? pgLoginByEmail(identifier, password) : pgLoginByUid(identifier, password);
}

/**
 * Creates a new user account. Only reachable via the admin-only
 * admin.createUser RPC case in browser-api-server.ts — there is no public
 * self-registration path anymore.
 */
export async function createUserAsAdmin(
  uid: string,
  fullName: string,
  email: string,
  password: string,
  role: UserRole,
): Promise<PgUser> {
  if (!process.env.PG_HOST && !process.env.PG_DB) {
    throw new Error('PostgreSQL not configured');
  }
  const hash = await bcrypt.hash(password, 10);
  try {
    const result = await getPool().query<DbRow>(
      `INSERT INTO users (uid, full_name, email, password_hash, role)
       VALUES ($1, $2, $3, $4, $5)
       RETURNING id, uid, full_name, email, role`,
      [uid, fullName, email, hash, role],
    );
    const row = result.rows[0]!;
    return {
      id: String(row.id),
      name: row.full_name ?? row.uid ?? row.email,
      email: row.email,
      role: toRole(row.role),
    };
  } catch (e: unknown) {
    if ((e as { code?: string }).code === '23505') {
      const detail = (e as { detail?: string }).detail ?? '';
      if (/\(uid\)|\(username\)/i.test(detail)) { throw new Error('Username already taken'); }
      if (/\(email\)/i.test(detail)) { throw new Error('Email already registered'); }
      throw new Error('An account with this username or email already exists');
    }
    throw e;
  }
}
