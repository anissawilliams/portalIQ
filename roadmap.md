# Preliminary Project Report
## CSCI/DATA XXXX — Implementation of Database Management Systems
**Anissa Williams**

---

### 1. Project Identification & Background

**Project:** PortalIQ — A Relational Database System for College Soccer Performance Analytics

PortalIQ is a sports analytics platform that ingests, stores, and queries multi-source performance data for the College of Charleston Men's Soccer program. The system centralizes match-event data (sourced from Wyscout), player performance scores, opponent profiles, and season statistics into a unified relational database — enabling automated reporting, player evaluation, and match intelligence workflows.

**Background:** I currently serve as Head of Sports Performance & Data Intelligence for the College of Charleston Men's Soccer program, where I am responsible for building the data infrastructure that supports coaching decisions, player evaluation, and tactical planning. I have hands-on experience building Python-based ETL pipelines, designing relational schemas, and deploying production APIs on top of database backends.

Relevant coursework and experience includes:
- MS Data Science (in progress) — College of Charleston
- Machine Learning, Statistical Modeling, Data Engineering coursework
- Production experience building FastAPI + Supabase (PostgreSQL) backends
- Applied AI Systems Engineering experience (Neta.ai, 2025–2026)
- 10+ years of enterprise software engineering leadership (Workiva, Zipari, Benefitfocus)

---

### 2. Project Description & Learning Outcomes

**Description:**

This project implements a fully normalized relational database system to support the College of Charleston Men's Soccer analytics pipeline. The database schema captures players, matches, opponents, match participation, individual performance events, computed COUGS Table scores, and configurable scoring weights — replacing a flat-file CSV workflow with a structured, queryable, and maintainable data model. The system integrates with a Python ingestion pipeline that extracts player statistics from Wyscout PDF reports, transforms them into structured records, and loads them into the database. A natural language query interface powered by an LLM will be layered on top of the schema, enabling coaches and staff to query performance data conversationally without SQL knowledge.

**Learning Outcomes:**

- *Data Management, Processing & Cleaning:* The ingestion pipeline handles raw PDF extraction, field normalization, anomaly detection, and structured loading into a relational schema — addressing real-world data quality challenges including missing values, inconsistent opponent naming, and multi-source format variations.
- *LLM Agentic AI and Database:* A natural language interface will be implemented using an LLM (Claude or OpenAI API) to translate plain-English queries into SQL against the PostgreSQL schema — enabling non-technical end users to interrogate the database conversationally.
- *Data Visualization:* Automated reporting workflows will generate match-level and season-level performance visualizations (COUGS Table leaderboards, player trend charts, ASET vs PEAK breakdowns) from database queries.
- *Data Exploration, Analysis & Modeling:* The database supports downstream modeling workflows including match outcome prediction (XGBoost), Monte Carlo simulation, and player valuation — all driven by structured queries against the normalized schema.

---

### 3. Citations & Timetable

**Citations:**

1. Elmasri, R., & Navathe, S. B. (2015). *Fundamentals of Database Systems* (7th ed.). Pearson. — Core reference for relational schema design, normalization, and query optimization principles applied in this project.

2. Supabase Documentation. (2024). *PostgreSQL as a Service — Schema Design and Row Level Security.* https://supabase.com/docs — Technical reference for the managed PostgreSQL platform used as the database backend, including multi-tenant authentication and RLS policies.

3. Passos, J., Papadopoulou, M., & Gómez, M. A. (2021). Machine learning approaches in soccer analytics: A systematic review. *International Journal of Sports Science & Coaching, 16*(5), 1–15. — Academic foundation for the player evaluation and match prediction modeling components of the system.

---

**Tentative Timetable:**

| Week | Milestone |
|------|-----------|
| Week 1–2 | Finalize database schema; create all tables in Supabase (PostgreSQL); document data dictionary |
| Week 3–4 | Build and test Python ingestion pipeline; load 2025 season match data into database |
| Week 5–6 | Implement LLM natural language query interface on top of schema |
| Week 7–8 | Build data visualization layer; automated COUGS Table reporting from DB queries |
| Week 9–10 | End-to-end testing, anomaly detection validation, performance tuning |
| Week 11 | Final documentation, presentation preparation |
| Week 12 | Project presentation |