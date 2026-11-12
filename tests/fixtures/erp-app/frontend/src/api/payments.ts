import { http } from './http';

export type PaymentMethod = 'CASH' | 'CARD' | 'BANK' | 'MOBILE_WALLET';

export interface Payment {
  id: number;
  invoiceId: number;
  amount: number;
  method: PaymentMethod;
  paidAt: string;
}

export const paymentApi = {
  list: () => http.get<Payment[]>('/payments').then((r) => r.data),
  get: (id: number) => http.get<Payment>(`/payments/${id}`).then((r) => r.data),
  create: (body: Omit<Payment, 'id'>) => http.post<Payment>('/payments', body).then((r) => r.data),
  update: (id: number, body: Omit<Payment, 'id'>) => http.put<Payment>(`/payments/${id}`, body).then((r) => r.data),
  remove: (id: number) => http.delete(`/payments/${id}`),
};
