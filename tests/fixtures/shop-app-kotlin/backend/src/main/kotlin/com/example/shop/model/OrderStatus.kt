package com.example.shop.model

enum class OrderStatus(val label: String) {
    PENDING("Pending"),
    PAID("Paid"),
    SHIPPED("Shipped"),
    CANCELLED("Cancelled");

    fun isFinal(): Boolean = this == SHIPPED || this == CANCELLED
}
