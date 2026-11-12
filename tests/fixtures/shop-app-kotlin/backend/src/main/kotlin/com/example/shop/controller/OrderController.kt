package com.example.shop.controller

import com.example.shop.model.Order
import com.example.shop.model.OrderStatus
import jakarta.validation.Valid
import jakarta.validation.constraints.NotBlank
import org.springframework.data.domain.Page
import org.springframework.data.domain.Pageable
import org.springframework.http.HttpStatus
import org.springframework.http.MediaType
import org.springframework.web.bind.annotation.*

@RestController
@RequestMapping("/api/orders")
class OrderController(private val service: OrderService) {

    /** Orders, newest first, optionally filtered by status. */
    @GetMapping
    fun list(@RequestParam(required = false) status: OrderStatus?, pageable: Pageable): Page<Order> =
        service.list(status, pageable)

    @GetMapping("/{id}")
    fun get(@PathVariable id: Long): Order = service.get(id)

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    fun create(@Valid @RequestBody request: CreateOrderRequest): Order {
        val order = service.create(request)
        return order
    }

    @PatchMapping("/{id}/status")
    fun changeStatus(@PathVariable id: Long, @RequestBody change: StatusChange): Order =
        service.changeStatus(id, change.status)
            .also { service.audit(it) }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    fun delete(@PathVariable("id") orderId: Long) {
        service.delete(orderId)
    }

    /** Plain-text receipt for the thermal printer. */
    @GetMapping(value = ["/{id}/receipt"], produces = [MediaType.TEXT_PLAIN_VALUE])
    fun receipt(@PathVariable id: Long): String = service.receipt(id)

    private fun helper(x: Int): Int = x * 2

    data class LineRequest(@field:NotBlank val sku: String, val quantity: Int)

    data class CreateOrderRequest(
        @field:NotBlank val customerName: String,
        val lines: List<LineRequest>,
        val note: String? = null,
    )

    data class StatusChange(val status: OrderStatus)
}
