'use client';
import { useEffect, useState } from 'react';
import TaskForm from './components/task-form';
import type { Task, TaskInput } from '@/lib/contracts';
export default function Page() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [editing, setEditing] = useState<Task | undefined>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  async function api(path: string, init?: RequestInit) {
    const response = await fetch(path, { ...init, headers: {'Content-Type':'application/json'} });
    if (!response.ok) { const data = await response.json(); throw new Error(data.error ?? 'Request failed'); }
    return response.status === 204 ? null : response.json();
  }
  async function load() { setTasks(await api('/api/tasks')); }
  useEffect(() => { load().catch(e=>setError(String(e))).finally(()=>setLoading(false)); }, []);
  async function save(input: TaskInput) {
    setBusy(true); setError(''); setNotice('');
    try { await api(editing ? `/api/tasks/${editing.id}` : '/api/tasks', {method:editing ? 'PATCH':'POST', body:JSON.stringify(input)}); await load(); setEditing(undefined); setNotice('Task saved'); }
    finally { setBusy(false); }
  }
  async function remove(id: number) {
    setBusy(true); setError('');
    try { await api(`/api/tasks/${id}`, {method:'DELETE'}); await load(); if (editing?.id === id) setEditing(undefined); setNotice('Task deleted'); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  async function edit(id: number) { try { setEditing(await api(`/api/tasks/${id}`)); } catch (e) { setError(String(e)); } }
  return <main><small>FORGEFSD · LOCAL TASK APP</small><h1>Your tasks</h1>
    <p>Plan your work, track progress, and keep it locally.</p>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <h2>{editing ? 'Edit task' : 'Create task'}</h2>
    <TaskForm key={editing?.id ?? 'new'} initial={editing} busy={busy} onSubmit={save}/>
    {editing && <button onClick={()=>setEditing(undefined)}>Cancel editing</button>}
    <h2>Tasks ({tasks.length})</h2>
    {loading ? <p>Loading…</p> : tasks.length === 0 ? <p>No tasks yet. Create your first task above.</p> : tasks.map(task=><article key={task.id}>
      <h3>{task.title}</h3><small>{task.status}</small><p>{task.description}</p>
      <button disabled={busy} onClick={()=>edit(task.id)}>View / edit</button><button disabled={busy} onClick={()=>remove(task.id)}>Delete</button>
    </article>)}
  </main>;
}
