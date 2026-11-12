export interface Refund {
  id: number;
  paymentId: number;
  amount: string;
  reason: string;
}

const BASE = '/api/refunds';

async function send<T>(url: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(url, { credentials: 'include', headers: { 'Content-Type': 'application/json' }, ...init });
  if (!res.ok) {
    const problem = (await res.json()) as { message?: string };
    throw new Error(problem.message ?? res.statusText);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export async function listRefunds(): Promise<Refund[]> {
  const res = await fetch(BASE, { credentials: 'include' });
  return (await res.json()) as Refund[];
}

export async function getRefund(id: number): Promise<Refund> {
  const res = await fetch(`${BASE}/${id}`, { credentials: 'include' });
  return (await res.json()) as Refund;
}

export async function createRefund(body: Omit<Refund, 'id'>): Promise<Refund> {
  const res = await fetch(BASE, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return (await res.json()) as Refund;
}

export async function updateRefund(id: number, body: Omit<Refund, 'id'>): Promise<Refund> {
  const res = await fetch(`${BASE}/${id}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return (await res.json()) as Refund;
}

export async function deleteRefund(id: number): Promise<void> {
  await fetch(`${BASE}/${id}`, { method: 'DELETE', credentials: 'include' });
}
