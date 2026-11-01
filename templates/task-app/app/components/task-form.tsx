'use client';
import { useState } from 'react';
import type { TaskInput, TaskStatus } from '@/lib/contracts';
type Props = { initial?: TaskInput; busy: boolean; onSubmit: (input: TaskInput) => Promise<void> };
export default function TaskForm({initial, busy, onSubmit}: Props) {
  const [title, setTitle] = useState(initial?.title ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [status, setStatus] = useState<TaskStatus>(initial?.status ?? 'todo');
  const [error, setError] = useState('');
  return <form onSubmit={async event => {
    event.preventDefault(); setError('');
    if (!title.trim() || title.trim().length > 120) { setError('Enter a title of 1-120 characters'); return; }
    try { await onSubmit({title: title.trim(), description, status}); if (!initial) { setTitle(''); setDescription(''); setStatus('todo'); } }
    catch (e) { setError(e instanceof Error ? e.message : 'Save failed'); }
  }}>
    <label>Title<input required maxLength={120} value={title} onChange={e=>setTitle(e.target.value)} /></label>
    <label>Description<textarea maxLength={2000} value={description} onChange={e=>setDescription(e.target.value)} /></label>
    <label>Status<select value={status} onChange={e=>setStatus(e.target.value as TaskStatus)}><option value="todo">To do</option><option value="in_progress">In progress</option><option value="done">Done</option></select></label>
    {error && <p role="alert">{error}</p>}<button disabled={busy}>{busy ? 'Saving…' : 'Save task'}</button>
  </form>;
}
