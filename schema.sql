-- ============================================================
-- Medi-Flow Orchestrator  ─  MySQL Database Schema
-- ============================================================
-- Run this script once to bootstrap the database:
--   mysql -u root -p < schema.sql
-- ============================================================

CREATE DATABASE IF NOT EXISTS mediflow
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE mediflow;

-- ── Users (doctors, lab staff, pharmacy staff) ──────────────
CREATE TABLE IF NOT EXISTS users (
    user_id     INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(120)  NOT NULL,
    email       VARCHAR(255)  NOT NULL UNIQUE,
    password    VARCHAR(255)  NOT NULL,          -- bcrypt hash
    role        ENUM('doctor','lab_staff','pharmacy_staff') NOT NULL,
    created_at  DATETIME      DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ── Patients ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS patients (
    patient_id      INT AUTO_INCREMENT PRIMARY KEY,
    ic_number       VARCHAR(20) UNIQUE,
    name            VARCHAR(120)  NOT NULL,
    age             INT,
    date_of_birth   DATE,
    phone_number    VARCHAR(20),
    home_address    TEXT,
    allergies       TEXT,
    medical_history TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ── Transcripts (doctor‑patient interactions) ──────────────
CREATE TABLE IF NOT EXISTS transcripts (
    transcript_id INT AUTO_INCREMENT PRIMARY KEY,
    patient_id    INT           NOT NULL,
    doctor_id     INT           NOT NULL,
    text          TEXT          NOT NULL,
    source        ENUM('voice','text','image') DEFAULT 'text',
    created_at    DATETIME      DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    FOREIGN KEY (doctor_id)  REFERENCES users(user_id)
) ENGINE=InnoDB;

-- ── Orders (generic: lab or pharmacy) ──────────────────────
CREATE TABLE IF NOT EXISTS orders (
    order_id    INT AUTO_INCREMENT PRIMARY KEY,
    patient_id  INT           NOT NULL,
    doctor_id   INT           NOT NULL,
    department  ENUM('laboratory','pharmacy') NOT NULL,
    order_type  VARCHAR(120)  NOT NULL,        -- e.g. "Blood Test" or "Antibiotics"
    details     TEXT,
    status      ENUM('pending','sent','in_progress','completed') DEFAULT 'pending',
    created_at  DATETIME      DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    FOREIGN KEY (doctor_id)  REFERENCES users(user_id)
) ENGINE=InnoDB;

-- ── Lab orders (extended info for laboratory) ──────────────
CREATE TABLE IF NOT EXISTS lab_orders (
    lab_order_id  INT AUTO_INCREMENT PRIMARY KEY,
    order_id      INT          NOT NULL,
    test_name     VARCHAR(120) NOT NULL,
    urgency       ENUM('routine','urgent') DEFAULT 'routine',
    result        TEXT,
    completed_at  DATETIME,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
) ENGINE=InnoDB;

-- ── Prescriptions (extended info for pharmacy) ─────────────
CREATE TABLE IF NOT EXISTS prescriptions (
    prescription_id INT AUTO_INCREMENT PRIMARY KEY,
    order_id        INT          NOT NULL,
    medicine_name   VARCHAR(200) NOT NULL,
    dosage          VARCHAR(120),
    duration        VARCHAR(120),
    dispensed_at    DATETIME,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
) ENGINE=InnoDB;

-- ── Reservations (operation / procedure scheduling) ────────
CREATE TABLE IF NOT EXISTS reservations (
    reservation_id  INT AUTO_INCREMENT PRIMARY KEY,
    patient_id      INT          NOT NULL,
    doctor_id       INT          NOT NULL,
    operation_type  VARCHAR(200) NOT NULL,
    scheduled_date  DATE         NOT NULL,
    scheduled_time  VARCHAR(10)  NOT NULL,
    duration_min    INT          DEFAULT 60,
    notes           TEXT,
    status          ENUM('scheduled','in_progress','completed','cancelled') DEFAULT 'scheduled',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    FOREIGN KEY (doctor_id)  REFERENCES users(user_id)
) ENGINE=InnoDB;

-- ── Appointments (AI chat-booked consultations) ───────────
CREATE TABLE IF NOT EXISTS appointments (
    appointment_id   INT AUTO_INCREMENT PRIMARY KEY,
    patient_id       INT          NOT NULL,
    doctor_id        INT          NOT NULL,
    patient_name     VARCHAR(100) NOT NULL,
    appointment_date DATE         NOT NULL,
    appointment_time VARCHAR(10)  NOT NULL,
    reason           TEXT,
    status           ENUM('scheduled','completed','cancelled') DEFAULT 'scheduled',
    created_at       DATETIME     DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    FOREIGN KEY (doctor_id)  REFERENCES users(user_id)
) ENGINE=InnoDB;

-- ── Visits (patient visits with diagnosis for pandemic heatmap) ─
CREATE TABLE IF NOT EXISTS visits (
    visit_id    INT AUTO_INCREMENT PRIMARY KEY,
    patient_id  INT          NOT NULL,
    doctor_id   INT          NOT NULL,
    diagnosis   VARCHAR(200) NOT NULL,
    severity    ENUM('low','medium','high') DEFAULT 'low',
    visit_date  DATE         NOT NULL,
    notes       TEXT,
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    FOREIGN KEY (doctor_id)  REFERENCES users(user_id)
) ENGINE=InnoDB;

-- ── Seed a default doctor account (password: doctor123) ────
-- The bcrypt hash below corresponds to "doctor123".
-- In production, create users through the application.
INSERT IGNORE INTO users (name, email, password, role)
VALUES
  ('Dr. Ahmad',     'doctor@mediflow.com',   '$2b$12$LJ3m4ys4Lz0QqXv0k8vCGeE3MnX9Z1v5b0z2R8vT7wYqN5x1u3p6e', 'doctor'),
  ('Lab Technician','lab@mediflow.com',      '$2b$12$LJ3m4ys4Lz0QqXv0k8vCGeE3MnX9Z1v5b0z2R8vT7wYqN5x1u3p6e', 'lab_staff'),
  ('Pharmacist',    'pharmacy@mediflow.com', '$2b$12$LJ3m4ys4Lz0QqXv0k8vCGeE3MnX9Z1v5b0z2R8vT7wYqN5x1u3p6e', 'pharmacy_staff');

-- ── Seed a demo patient ────────────────────────────────────
INSERT IGNORE INTO patients (ic_number, name, age, date_of_birth, phone_number, home_address, allergies, medical_history)
VALUES ('900101-01-1234', 'Ali bin Abu', 35, '1990-01-01', '012-3456789', '123 Jalan Merdeka, KL', 'None', 'No known allergies. Previous appendectomy in 2020.');
