-- ════════════════════════════════════════════════════
-- SnapLedger — Supabase Database Setup
-- Run this once in the Supabase SQL Editor
-- ════════════════════════════════════════════════════

create table if not exists companies (
  id               uuid    default gen_random_uuid() primary key,
  company_code     text    unique not null,
  company_name     text    not null,
  owner_username   text    not null,
  owner_password   text    not null,
  created_at       timestamptz default now()
);

create table if not exists documents (
  id               uuid    default gen_random_uuid() primary key,
  company_code     text    not null,
  doc_type         text    default 'other',
  supplier_name    text,
  doc_date         date,
  doc_number       text,
  total_amount     numeric(14,2),
  currency         text    default 'UGX',
  notes            text,
  image_data       text,
  raw_extraction   text,
  created_at       timestamptz default now()
);
create index if not exists idx_docs_company  on documents(company_code);
create index if not exists idx_docs_supplier on documents(company_code, supplier_name);
create index if not exists idx_docs_date     on documents(company_code, doc_date);

create table if not exists doc_items (
  id                     uuid    default gen_random_uuid() primary key,
  document_id            uuid    references documents(id) on delete cascade,
  company_code           text    not null,
  supplier_product_name  text,
  our_product_name       text,
  quantity               numeric(12,3),
  unit                   text,
  unit_price             numeric(14,2),
  total_price            numeric(14,2),
  needs_review           boolean default false,
  created_at             timestamptz default now()
);
create index if not exists idx_items_document on doc_items(document_id);
create index if not exists idx_items_company  on doc_items(company_code);
create index if not exists idx_items_review   on doc_items(company_code, needs_review);

-- Maps supplier product names to your internal names
create table if not exists product_dictionary (
  id                     uuid    default gen_random_uuid() primary key,
  company_code           text    not null,
  supplier_product_name  text    not null,
  our_product_name       text    not null,
  confirmed              boolean default true,
  created_at             timestamptz default now()
);
create index if not exists idx_dict_company on product_dictionary(company_code);
create index if not exists idx_dict_lookup  on product_dictionary(company_code, supplier_product_name);

-- ════════════════════════════════════════════════════
-- Disable RLS (run if inserts fail silently)
-- ════════════════════════════════════════════════════
-- alter table companies          disable row level security;
-- alter table documents          disable row level security;
-- alter table doc_items          disable row level security;
-- alter table product_dictionary disable row level security;

-- ════════════════════════════════════════════════════
-- Sample company (uncomment to create one)
-- ════════════════════════════════════════════════════
insert into companies (company_code, company_name, owner_username, owner_password)
values ('PHONES2026', 'Bamulah Phones and Accessories', 'admin', 'admin123');
