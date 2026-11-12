// Plain JavaScript API layer (no types) for the shop-app backend.

const BASE = '/api/orders';

export async function fetchOrders() {
  const res = await fetch(BASE, { credentials: 'include' });
  return res.json();
}

export async function createOrder(customerName, items) {
  const res = await fetch(BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ customerName, items }),
  });
  return res.json();
}

export async function setStatus(id, status) {
  const res = await fetch(`${BASE}/${id}/status`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  });
  return res.json();
}

export async function cancelOrder(id) {
  await fetch(`${BASE}/${id}/cancel`, { method: 'POST' });
}

export async function fetchReceipt(id) {
  const res = await fetch(`${BASE}/${id}/receipt`);
  return res.json();
}
