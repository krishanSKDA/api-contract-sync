export interface StockMovement {
  id: number;
  productId: number;
  warehouseId: number;
  quantity: number;
  movedAt: string;
}

const BASE = '/api/stock-movements';

async function send<T>(url: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(url, { credentials: 'include', headers: { 'Content-Type': 'application/json' }, ...init });
  if (!res.ok) {
    const problem = (await res.json()) as { message?: string };
    throw new Error(problem.message ?? res.statusText);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export async function listStockMovements(): Promise<StockMovement[]> {
  const res = await fetch(BASE, { credentials: 'include' });
  return (await res.json()) as StockMovement[];
}

export async function getStockMovement(id: number): Promise<StockMovement> {
  const res = await fetch(`${BASE}/${id}`, { credentials: 'include' });
  return (await res.json()) as StockMovement;
}

export async function createStockMovement(body: Omit<StockMovement, 'id'>): Promise<StockMovement> {
  const res = await fetch(BASE, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return (await res.json()) as StockMovement;
}

export async function updateStockMovement(id: number, body: Omit<StockMovement, 'id'>): Promise<StockMovement> {
  const res = await fetch(`${BASE}/${id}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return (await res.json()) as StockMovement;
}

export async function deleteStockMovement(id: number): Promise<void> {
  await fetch(`${BASE}/${id}`, { method: 'DELETE', credentials: 'include' });
}
