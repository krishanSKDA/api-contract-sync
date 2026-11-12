import { http } from './http';

export interface Warehouse {
  id: number;
  name: string;
  location: string;
}

export const warehouseApi = {
  list: () => http.get<Warehouse[]>('/warehouses').then((r) => r.data),
  get: (id: number) => http.get<Warehouse>(`/warehouses/${id}`).then((r) => r.data),
  create: (body: Omit<Warehouse, 'id'>) => http.post<Warehouse>('/warehouses', body).then((r) => r.data),
  update: (id: number, body: Omit<Warehouse, 'id'>) => http.put<Warehouse>(`/warehouses/${id}`, body).then((r) => r.data),
  remove: (id: number) => http.delete(`/warehouses/${id}`),
};
