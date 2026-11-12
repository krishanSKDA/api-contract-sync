package com.acme.erp.repository;

import com.acme.erp.model.Shift;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ShiftRepository extends JpaRepository<Shift, Long> { }
