package com.example.shop.model

import com.fasterxml.jackson.annotation.JsonIgnore
import jakarta.persistence.*
import java.math.BigDecimal
import java.time.LocalDateTime

/** A customer order. */
@Entity
@Table(name = "orders")
data class Order(
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    val id: Long? = null,

    /** Name printed on the receipt. */
    @Column(nullable = false)
    val customerName: String,

    val total: BigDecimal = BigDecimal.ZERO,

    @Enumerated(EnumType.STRING)
    var status: OrderStatus = OrderStatus.PENDING,

    val createdAt: LocalDateTime = LocalDateTime.now(),

    @OneToMany(cascade = [CascadeType.ALL])
    val lines: List<OrderLine> = emptyList(),

    @field:JsonIgnore
    val internalNote: String? = null,

    var paid: Boolean = false,
) {
    /** Number of items across all lines. */
    val itemCount: Int
        get() = lines.sumOf { it.quantity }

    private val auditTrail: MutableList<String> = mutableListOf()

    fun markPaid() {
        paid = true
    }
}
