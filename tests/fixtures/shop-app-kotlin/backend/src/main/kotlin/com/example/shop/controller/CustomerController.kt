package com.example.shop.controller

import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/customers")
class CustomerController {

    @GetMapping
    fun search(@RequestParam(defaultValue = "") q: String): List<CustomerDto> = emptyList()

    data class CustomerDto(val id: Long?, val fullName: String?, val email: String?, val loyaltyPoints: Int)
}
