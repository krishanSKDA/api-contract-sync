package com.example.shop.controller;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/customers")
public class CustomerController {

    @GetMapping
    public List<CustomerDto> search(@RequestParam(defaultValue = "") String q) {
        return List.of();
    }

    public record CustomerDto(Long id, String fullName, String email, int loyaltyPoints) {
    }
}
