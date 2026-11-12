import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export type OrderStatus = 'PENDING' | 'PAID' | 'SHIPPED' | 'CANCELLED';

export interface OrderLine {
  id: number;
  sku: string;
  quantity: number;
  unitPrice: number;
}

export interface Order {
  id: number;
  customerName: string;
  total: number;
  status: OrderStatus;
  createdAt: string;
  lines: OrderLine[];
  paid: boolean;
}

@Injectable({ providedIn: 'root' })
export class OrderService {
  private readonly api = '/api/orders';

  constructor(private http: HttpClient) {}

  list(): Observable<Order[]> {
    return this.http.get<Order[]>(this.api);
  }

  get(id: number): Observable<Order> {
    return this.http.get<Order>(`${this.api}/${id}`);
  }

  create(customerName: string, items: { sku: string; quantity: number }[]): Observable<Order> {
    return this.http.post<Order>(this.api, { customerName, items });
  }

  setStatus(id: number, status: OrderStatus): Observable<Order> {
    return this.http.put<Order>(`${this.api}/${id}/status`, { status });
  }

  receipt(id: number): Observable<string> {
    return this.http.get<string>(`${this.api}/${id}/receipt`);
  }

  receiptAsText(id: number): Observable<string> {
    return this.http.get(`${this.api}/${id}/receipt`, { responseType: 'text' });
  }

  remove(id: number): Observable<void> {
    return this.http.delete<void>(`${this.api}/${id}`);
  }
}
