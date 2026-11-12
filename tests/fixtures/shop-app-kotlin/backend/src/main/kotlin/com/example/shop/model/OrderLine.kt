package com.example.shop.model

import jakarta.persistence.*
import java.math.BigDecimal

@Entity
data class OrderLine(
    @Id @GeneratedValue val id: Long? = null,
    val sku: String,
    val quantity: Int,
    val unitPrice: BigDecimal,
)
