import { getTask, updateTask, deleteTask, TaskError } from '@/lib/tasks';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
type Context = { params: Promise<{id: string}> };
function failure(error: unknown) { return Response.json({error: error instanceof TaskError ? error.message : 'Internal server error'}, {status: error instanceof TaskError ? error.status : 500}); }
async function idOf(context: Context) { const {id} = await context.params; return /^\d+$/.test(id) ? Number(id) : NaN; }
export async function GET(_request: Request, context: Context) {
  try { return Response.json(getTask(await idOf(context))); } catch (error) { return failure(error); }
}
export async function PATCH(request: Request, context: Context) {
  let input: unknown;
  try { input = await request.json(); } catch { return Response.json({error:'Invalid JSON'}, {status:400}); }
  try { return Response.json(updateTask(await idOf(context), input)); } catch (error) { return failure(error); }
}
export async function DELETE(_request: Request, context: Context) {
  try { deleteTask(await idOf(context)); return new Response(null, {status:204}); } catch (error) { return failure(error); }
}
