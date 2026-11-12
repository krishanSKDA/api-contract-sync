import { http } from './http';

export interface NewCoupon {
  code: string;
  expiry: string;
}

export interface Coupon {
  id: number;
  code: string;
  expiresAt: string;
}

export const couponApi = {
  list: () => http.get<Coupon[]>('/coupons').then((r) => r.data),
  get: (id: number) => http.get<Coupon>(`/coupons/${id}`).then((r) => r.data),
  create: (body: NewCoupon) => http.post<Coupon>('/coupons', body).then((r) => r.data),
  update: (id: number, body: Omit<Coupon, 'id'>) => http.put<Coupon>(`/coupons/${id}`, body).then((r) => r.data),
  remove: (id: number) => http.delete(`/coupons/${id}`),
};
