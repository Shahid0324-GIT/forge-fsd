import { DatabaseSync } from 'node:sqlite';
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
let database: DatabaseSync | undefined;
export function getDb(): DatabaseSync {
  if (!database) {
    const path = resolve(process.env.SQLITE_PATH ?? './data/tasks.sqlite3');
    mkdirSync(dirname(path), { recursive: true });
    database = new DatabaseSync(path);
    database.exec(`PRAGMA journal_mode=WAL;
      CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL, description TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('todo','in_progress','done')),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
      );`);
  }
  return database;
}
