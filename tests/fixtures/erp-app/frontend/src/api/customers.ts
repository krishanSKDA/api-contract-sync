import { http } from './http';

export interface Customer {
  id: number;
  fullName: string;
  email: string;
  phone: string;
  loyaltyPoints: number;
}

export const customerApi = {
  list: () => http.get<Customer[]>('/customers').then((r) => r.data),
  get: (id: number) => http.get<Customer>(`/customers/${id}`).then((r) => r.data),
  create: (body: Omit<Customer, 'id'>) => http.post<Customer>('/customers', body).then((r) => r.data),
  update: (id: number, body: Omit<Customer, 'id'>) => http.put<Customer>(`/customers/${id}`, body).then((r) => r.data),
  remove: (id: number) => http.delete(`/customers/${id}`),
};
