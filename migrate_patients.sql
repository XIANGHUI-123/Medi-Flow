-- Migration: Add new columns to patients table
-- Run: mysql -u root -p mediflow < migrate_patients.sql

USE mediflow;

ALTER TABLE patients
  ADD COLUMN IF NOT EXISTS ic_number     VARCHAR(20) UNIQUE AFTER patient_id,
  ADD COLUMN IF NOT EXISTS date_of_birth DATE               AFTER age,
  ADD COLUMN IF NOT EXISTS phone_number  VARCHAR(20)        AFTER date_of_birth,
  ADD COLUMN IF NOT EXISTS home_address  TEXT               AFTER phone_number,
  ADD COLUMN IF NOT EXISTS allergies     TEXT               AFTER home_address;

-- Update seed patient with demo data
UPDATE patients
  SET ic_number     = '900101-01-1234',
      date_of_birth = '1990-01-01',
      phone_number  = '012-3456789',
      home_address  = '123 Jalan Merdeka, KL',
      allergies     = 'None'
  WHERE name = 'Ali bin Abu' AND ic_number IS NULL;
