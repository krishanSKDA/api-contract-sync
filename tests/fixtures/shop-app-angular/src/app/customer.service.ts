import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { environment } from '../environments/environment';

export interface Customer {
  id: number;
  fullName: string;
  email: string;
  loyaltyPoints: number;
  phone: string;
}

@Injectable({ providedIn: 'root' })
export class CustomerService {
  private http = inject(HttpClient);

  search(q: string) {
    return this.http.get<Customer[]>(`${environment.apiUrl}/api/customers`, { params: { q } });
  }
}
