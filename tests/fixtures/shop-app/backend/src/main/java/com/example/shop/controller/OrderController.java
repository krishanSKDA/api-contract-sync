package com.example.shop.controller;

import com.example.shop.model.Order;
import com.example.shop.model.OrderStatus;
import com.example.shop.service.OrderService;
import jakarta.validation.constraints.NotBlank;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/orders")
public class OrderController {

    private final OrderService orders;

    public OrderController(OrderService orders) {
        this.orders = orders;
    }

    /** Orders, newest first, optionally filtered by status. */
    @GetMapping
    public Page<Order> list(@RequestParam(required = false) OrderStatus status, Pageable pageable) {
        return orders.list(status, pageable);
    }

    @GetMapping("/{id}")
    public Order get(@PathVariable Long id) {
        return orders.get(id);
    }

    @PostMapping
    public ResponseEntity<Order> create(@RequestBody CreateOrderRequest request) {
        return ResponseEntity.status(201).body(orders.create(request));
    }

    @PatchMapping("/{id}/status")
    public Order changeStatus(@PathVariable Long id, @RequestBody StatusChange change) {
        return orders.changeStatus(id, change.status());
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(@PathVariable("id") Long orderId) {
        orders.delete(orderId);
        return ResponseEntity.noContent().build();
    }

    /** Plain-text receipt for the thermal printer. */
    @GetMapping("/{id}/receipt")
    public String receipt(@PathVariable Long id) {
        return orders.receiptText(id);
    }

    public record CreateOrderRequest(@NotBlank String customerName, List<LineRequest> lines, String note) {
    }

    public record LineRequest(String sku, int quantity) {
    }

    public record StatusChange(OrderStatus status) {
    }
}
