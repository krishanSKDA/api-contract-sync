export type InvoiceStatus = 'DRAFT' | 'ISSUED' | 'PAID' | 'VOID';

export interface Invoice {
  id: number;
  number: string;
  customerId: number;
  total: string;
  status: InvoiceStatus;
  issuedAt: string;
}

const BASE = '/api/invoices';

async function send<T>(url: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(url, { credentials: 'include', headers: { 'Content-Type': 'application/json' }, ...init });
  if (!res.ok) {
    const problem = (await res.json()) as { message?: string };
    throw new Error(problem.message ?? res.statusText);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export async function listInvoices(): Promise<Invoice[]> {
  const res = await fetch(BASE, { credentials: 'include' });
  return (await res.json()) as Invoice[];
}

export async function getInvoice(id: number): Promise<Invoice> {
  const res = await fetch(`${BASE}/${id}`, { credentials: 'include' });
  return (await res.json()) as Invoice;
}

export async function createInvoice(body: Omit<Invoice, 'id'>): Promise<Invoice> {
  const res = await fetch(BASE, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return (await res.json()) as Invoice;
}

export async function updateInvoice(id: number, body: Omit<Invoice, 'id'>): Promise<Invoice> {
  const res = await fetch(`${BASE}/${id}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return (await res.json()) as Invoice;
}

export async function deleteInvoice(id: number): Promise<void> {
  await fetch(`${BASE}/${id}`, { method: 'DELETE', credentials: 'include' });
}

export async function printInvoice(id: number): Promise<{ text: string }> {
  const res = await fetch(`${BASE}/${id}/print`, { credentials: 'include' });
  return (await res.json()) as { text: string };
}
