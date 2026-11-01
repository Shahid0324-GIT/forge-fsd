import { getDb } from './db';
import type { Task, TaskInput, TaskStatus } from './contracts';
export class TaskError extends Error {
  constructor(message: string, public status: number) { super(message); }
}
const columns = 'id,title,description,status,created_at AS createdAt,updated_at AS updatedAt';
function validate(value: unknown, partial = false): Partial<TaskInput> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new TaskError('Expected an object', 400);
  const input = value as Record<string, unknown>;
  if (Object.keys(input).some(k => !['title','description','status'].includes(k))) throw new TaskError('Unknown field', 400);
  const result: Partial<TaskInput> = {};
  if (!partial || 'title' in input) {
    if (typeof input.title !== 'string' || !input.title.trim() || input.title.trim().length > 120) throw new TaskError('Title must be 1-120 characters', 400);
    result.title = input.title.trim();
  }
  if (!partial || 'description' in input) {
    const text = input.description ?? '';
    if (typeof text !== 'string' || text.length > 2000) throw new TaskError('Description must be at most 2000 characters', 400);
    result.description = text;
  }
  if (!partial || 'status' in input) {
    const status = input.status ?? 'todo';
    if (!['todo','in_progress','done'].includes(String(status))) throw new TaskError('Invalid status', 400);
    result.status = status as TaskStatus;
  }
  if (partial && !Object.keys(result).length) throw new TaskError('Empty update', 400);
  return result;
}
function checkedId(id: number) { if (!Number.isSafeInteger(id) || id <= 0) throw new TaskError('Invalid id', 400); }
export function listTasks(): Task[] { return getDb().prepare(`SELECT ${columns} FROM tasks ORDER BY id DESC`).all() as unknown as Task[]; }
export function getTask(id: number): Task {
  checkedId(id);
  const task = getDb().prepare(`SELECT ${columns} FROM tasks WHERE id=?`).get(id) as unknown as Task | undefined;
  if (!task) throw new TaskError('Task not found', 404);
  return task;
}
export function createTask(input: unknown): Task {
  const task = validate(input) as TaskInput;
  const now = new Date().toISOString();
  const result = getDb().prepare('INSERT INTO tasks(title,description,status,created_at,updated_at) VALUES (?,?,?,?,?)').run(task.title, task.description, task.status, now, now);
  return getTask(Number(result.lastInsertRowid));
}
export function updateTask(id: number, input: unknown): Task {
  const existing = getTask(id);
  const task = { ...existing, ...validate(input, true) };
  getDb().prepare('UPDATE tasks SET title=?,description=?,status=?,updated_at=? WHERE id=?').run(task.title, task.description, task.status, new Date().toISOString(), id);
  return getTask(id);
}
export function deleteTask(id: number): void { getTask(id); getDb().prepare('DELETE FROM tasks WHERE id=?').run(id); }
