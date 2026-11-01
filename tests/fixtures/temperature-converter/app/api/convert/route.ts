import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  let body: unknown;
  try { body = await request.json(); } catch { return NextResponse.json({ error: 'Invalid input' }, { status: 400 }); }
  if (!body || typeof body !== 'object' || Array.isArray(body)) return NextResponse.json({ error: 'Invalid input' }, { status: 400 });

  const { value, from } = body as { value: number; from: 'C' | 'F' };

  if (typeof value !== 'number' || !Number.isFinite(value)) return NextResponse.json({ error: 'Invalid input' }, { status: 400 });
  if (from !== 'C' && from !== 'F') return NextResponse.json({ error: 'Invalid input' }, { status: 400 });

  let result: number;
  if (from === 'C') {
    result = value * 9 / 5 + 32;
  } else {
    result = (value - 32) * 5 / 9;
  }

  return NextResponse.json({ result, unit: from === 'C' ? 'F' : 'C' });
}