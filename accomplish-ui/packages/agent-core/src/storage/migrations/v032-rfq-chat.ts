import type { Database } from 'better-sqlite3';
import type { Migration } from './index.js';

/**
 * v032 — RFQ chat feature (BuLLMQuote-SRIM): adds `tasks.rfq_id` (mirrors
 * v011's `workspace_id` column exactly — same idempotent add-column-then-
 * index pattern) so a task can be scoped to an RFQ, and
 * `task_messages.citations` (JSON-serialized MessageCitation[]) so source
 * references on RFQ-chat answers survive a reload, not just an in-memory
 * session.
 */
export const migration: Migration = {
  version: 32,
  up: (db: Database) => {
    const taskCols = db.prepare('PRAGMA table_info(tasks)').all() as Array<{ name: string }>;
    if (!taskCols.some((col) => col.name === 'rfq_id')) {
      db.exec(`ALTER TABLE tasks ADD COLUMN rfq_id TEXT`);
    }
    db.exec(`CREATE INDEX IF NOT EXISTS idx_tasks_rfq_id ON tasks(rfq_id)`);

    const messageCols = db.prepare('PRAGMA table_info(task_messages)').all() as Array<{ name: string }>;
    if (!messageCols.some((col) => col.name === 'citations')) {
      db.exec(`ALTER TABLE task_messages ADD COLUMN citations TEXT`);
    }
  },
};
