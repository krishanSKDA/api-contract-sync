export interface Supplier {
  id: number;
  name: string;
  email: string;
  phone: string;
}

const BASE = '/api/suppliers';

async function send<T>(url: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(url, { credentials: 'include', headers: { 'Content-Type': 'application/json' }, ...init });
  if (!res.ok) {
    const problem = (await res.json()) as { message?: string };
    throw new Error(problem.message ?? res.statusText);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export async function listSuppliers(): Promise<Supplier[]> {
  const res = await fetch(BASE, { credentials: 'include' });
  return (await res.json()) as Supplier[];
}

export async function getSupplier(id: number): Promise<Supplier> {
  const res = await fetch(`${BASE}/${id}`, { credentials: 'include' });
  return (await res.json()) as Supplier;
}

export async function createSupplier(body: Omit<Supplier, 'id'>): Promise<Supplier> {
  const res = await fetch(BASE, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return (await res.json()) as Supplier;
}

export async function updateSupplier(id: number, body: Omit<Supplier, 'id'>): Promise<Supplier> {
  const res = await fetch(`${BASE}/${id}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return (await res.json()) as Supplier;
}

export async function deleteSupplier(id: number): Promise<void> {
  await fetch(`${BASE}/${id}`, { method: 'DELETE', credentials: 'include' });
}
