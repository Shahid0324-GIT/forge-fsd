import { listTasks, createTask, TaskError } from '@/lib/tasks';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET() {
  try { return Response.json(listTasks()); }
  catch { return Response.json({error:'Internal server error'}, {status:500}); }
}
export async function POST(request: Request) {
  let input: unknown;
  try { input = await request.json(); } catch { return Response.json({error:'Invalid JSON'}, {status:400}); }
  try { return Response.json(createTask(input), {status:201}); }
  catch (error) { return Response.json({error: error instanceof TaskError ? error.message : 'Internal server error'}, {status: error instanceof TaskError ? error.status : 500}); }
}
