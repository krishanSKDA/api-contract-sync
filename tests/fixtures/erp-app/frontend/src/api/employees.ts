export type Role = 'OWNER' | 'MANAGER' | 'CASHIER';

export interface Employee {
  id: number;
  fullName: string;
  role: Role;
  passwordHash: string;
}

const BASE = '/api/employees';

async function send<T>(url: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(url, { credentials: 'include', headers: { 'Content-Type': 'application/json' }, ...init });
  if (!res.ok) {
    const problem = (await res.json()) as { message?: string };
    throw new Error(problem.message ?? res.statusText);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export async function listEmployees(): Promise<Employee[]> {
  const res = await fetch(BASE, { credentials: 'include' });
  return (await res.json()) as Employee[];
}

export async function getEmployee(id: number): Promise<Employee> {
  const res = await fetch(`${BASE}/${id}`, { credentials: 'include' });
  return (await res.json()) as Employee;
}

export async function createEmployee(body: Omit<Employee, 'id'>): Promise<Employee> {
  const res = await fetch(BASE, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return (await res.json()) as Employee;
}

export async function updateEmployee(id: number, body: Omit<Employee, 'id'>): Promise<Employee> {
  const res = await fetch(`${BASE}/${id}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return (await res.json()) as Employee;
}

export async function deleteEmployee(id: number): Promise<void> {
  await fetch(`${BASE}/${id}`, { method: 'DELETE', credentials: 'include' });
}
