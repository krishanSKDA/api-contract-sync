package com.example.shop.model;

import jakarta.persistence.*;

@Entity
public class OrderLine {

    @Id
    @GeneratedValue
    private Long id;

    @Column(nullable = false)
    private String sku;

    private int quantity;

    private double unitPrice;

    public Long getId() { return id; }
    public String getSku() { return sku; }
    public void setSku(String sku) { this.sku = sku; }
    public int getQuantity() { return quantity; }
    public void setQuantity(int quantity) { this.quantity = quantity; }
    public double getUnitPrice() { return unitPrice; }
    public void setUnitPrice(double unitPrice) { this.unitPrice = unitPrice; }
}
