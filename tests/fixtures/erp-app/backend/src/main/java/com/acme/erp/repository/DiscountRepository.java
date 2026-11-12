package com.acme.erp.repository;

import com.acme.erp.model.Discount;
import org.springframework.data.jpa.repository.JpaRepository;

public interface DiscountRepository extends JpaRepository<Discount, Long> { }
