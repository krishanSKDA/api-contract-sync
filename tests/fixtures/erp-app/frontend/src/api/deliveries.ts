export interface Delivery {
  id: number;
  invoiceId: number;
  tracking_no: string;
  carrier: string;
}

const BASE = '/api/deliveries';

async function send<T>(url: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(url, { credentials: 'include', headers: { 'Content-Type': 'application/json' }, ...init });
  if (!res.ok) {
    const problem = (await res.json()) as { message?: string };
    throw new Error(problem.message ?? res.statusText);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export async function listDeliveries(): Promise<Delivery[]> {
  const res = await fetch(BASE, { credentials: 'include' });
  return (await res.json()) as Delivery[];
}

export async function getDelivery(id: number): Promise<Delivery> {
  const res = await fetch(`${BASE}/${id}`, { credentials: 'include' });
  return (await res.json()) as Delivery;
}

export async function createDelivery(body: Omit<Delivery, 'id'>): Promise<Delivery> {
  const res = await fetch(BASE, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return (await res.json()) as Delivery;
}

export async function updateDelivery(id: number, body: Omit<Delivery, 'id'>): Promise<Delivery> {
  const res = await fetch(`${BASE}/${id}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return (await res.json()) as Delivery;
}

export async function deleteDelivery(id: number): Promise<void> {
  await fetch(`${BASE}/${id}`, { method: 'DELETE', credentials: 'include' });
}
