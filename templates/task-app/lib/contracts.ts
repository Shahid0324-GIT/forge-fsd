export type TaskStatus = 'todo' | 'in_progress' | 'done';
export type TaskInput = { title: string; description: string; status: TaskStatus };
export type Task = TaskInput & { id: number; createdAt: string; updatedAt: string };
