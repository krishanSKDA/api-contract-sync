import { http } from './http';

export type PoStatus = 'OPEN' | 'APPROVED' | 'RECEIVED' | 'CANCELLED';

export interface PurchaseOrder {
  id: number;
  supplierId: number;
  total: number;
  status: PoStatus;
}

export const purchaseOrderApi = {
  list: () => http.get<PurchaseOrder[]>('/purchase-orders').then((r) => r.data),
  get: (id: number) => http.get<PurchaseOrder>(`/purchase-orders/${id}`).then((r) => r.data),
  create: (body: Omit<PurchaseOrder, 'id'>) => http.post<PurchaseOrder>('/purchase-orders', body).then((r) => r.data),
  update: (id: number, body: Omit<PurchaseOrder, 'id'>) => http.put<PurchaseOrder>(`/purchase-orders/${id}`, body).then((r) => r.data),
  remove: (id: number) => http.delete(`/purchase-orders/${id}`),
  approve: (id: number) => http.post<PurchaseOrder>(`/purchase-orders/${id}/approve`).then((r) => r.data),
};
