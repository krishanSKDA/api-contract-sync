// Hand-written API layer for the orders screens.

export type OrderStatus = 'PENDING' | 'PAID' | 'SHIPPED' | 'REFUNDED';

export interface OrderLine {
  id: number;
  sku: string;
  quantity: number;
  unitPrice: number;
}

export interface Order {
  id: number;
  customer_name: string;
  total: string;
  status: OrderStatus;
  createdAt: Date;
  lines: OrderLine[];
  paid: boolean;
}

export interface Receipt {
  text: string;
}

const BASE = '/api/orders';

export async function fetchOrders(): Promise<Order[]> {
  const res = await fetch(BASE, { credentials: 'include' });
  if (!res.ok) {
    const err = (await res.json()) as { message?: string };
    throw new Error(err.message ?? 'Failed');
  }
  return (await res.json()) as Order[];
}

export async function fetchOrder(id: number): Promise<Order> {
  const res = await fetch(`${BASE}/${id}`, { credentials: 'include' });
  return (await res.json()) as Order;
}

export async function createOrder(customerName: string, items: { sku: string; quantity: number }[]): Promise<Order> {
  const res = await fetch(BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ customerName, items }),
  });
  return (await res.json()) as Order;
}

export async function setStatus(id: number, status: OrderStatus): Promise<Order> {
  const res = await fetch(`${BASE}/${id}/status`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  });
  return (await res.json()) as Order;
}

export async function cancelOrder(id: number): Promise<void> {
  await fetch('/api/orders/' + id + '/cancel', { method: 'POST' });
}

export async function deleteOrder(id: number): Promise<void> {
  await fetch(`${BASE}/${id}`, { method: 'DELETE' });
}

export async function fetchReceipt(id: number): Promise<Receipt> {
  const res = await fetch(`${BASE}/${id}/receipt`);
  return (await res.json()) as Receipt;
}
