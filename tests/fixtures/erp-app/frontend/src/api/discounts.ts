export interface Discount {
  id: number;
  name: string;
  percent: number;
  active: boolean;
}

const BASE = '/api/discounts';

async function send<T>(url: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(url, { credentials: 'include', headers: { 'Content-Type': 'application/json' }, ...init });
  if (!res.ok) {
    const problem = (await res.json()) as { message?: string };
    throw new Error(problem.message ?? res.statusText);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export async function listDiscounts(): Promise<Discount[]> {
  const res = await fetch(BASE, { credentials: 'include' });
  return (await res.json()) as Discount[];
}

export async function getDiscount(id: number): Promise<Discount> {
  const res = await fetch(`${BASE}/${id}`, { credentials: 'include' });
  return (await res.json()) as Discount;
}

export async function createDiscount(body: Omit<Discount, 'id'>): Promise<Discount> {
  const res = await fetch(BASE, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return (await res.json()) as Discount;
}

export async function updateDiscount(id: number, body: Omit<Discount, 'id'>): Promise<Discount> {
  const res = await fetch(`${BASE}/${id}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return (await res.json()) as Discount;
}

export async function deleteDiscount(id: number): Promise<void> {
  await fetch(`${BASE}/${id}`, { method: 'DELETE', credentials: 'include' });
}
