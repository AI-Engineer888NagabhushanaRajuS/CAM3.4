import pg from 'pg';

if (!process.env.DATABASE_URL || !process.env.FILE_METADATA_DB_URL) {
  throw new Error('DATABASE_URL and FILE_METADATA_DB_URL must be set (see .env.example)');
}

export const pgPool = new pg.Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: false,
});

export const fileMetadataPool = new pg.Pool({
  connectionString: process.env.FILE_METADATA_DB_URL,
  ssl: false,
});