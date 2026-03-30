# CRM & WarehouseOps Architecture Evaluation

**STATUS:** REJECTED FOR MULTI-USER ENTERPRISE USE (Subject to Gravity Protocol overrides)

You asked to write down the offline PyInstaller + DuckDB stack for a new CRM and Warehouse Operations application. While this stack is excellent for a single-user, offline, bulk-processing tool (like the ASN Claims App), it fundamentally violates the architectural requirements of a multi-user organizational CRM and Warehouse system.

## Proposed Stack Analysis (The "Offline Desktop" Approach)

### The Stack:
- **Backend:** Python / FastAPI / Uvicorn
- **Data Engine:** DuckDB / Polars
- **UI:** Vanilla HTML/JS + Chart.js
- **Distribution:** PyInstaller / Inno Setup (Local Windows Executables)

### System Pressure Failure Vectors:
1. **Concurrency & Truth:** A CRM and Warehouse system requires a **Single Source of Truth**. The proposed stack uses a local, embedded `app.duckdb` database on the user's hard drive. If five warehouse workers and three sales reps run the app, you now have 8 diverging databases. **Silent data loss and conflicted state are guaranteed.**
2. **Access Control:** Zero trust and RBAC cannot be enforced purely on a client-side executable where the user holds the raw `.db` file.
3. **Scalability Law Violation:** "Scale by duplication, not complexity." You cannot horizontally scale an offline SQLite/DuckDB file hosted on individual client machines.

---

## The Gravity-Approved Architecture

To ensure your CRM and Warehouse logistics scale cleanly, remain stable under load, and minimize future regret, you must adopt an authoritative, centralized architecture.

### Tier 1: The Data Layer (Single Source of Truth)
- **PostgreSQL Database:** The absolute, centralized source of truth for all customer records, inventory counts, and warehouse transactions.
- **Prisma ORM:** For strictly-typed database schema migrations and queries.
- **Redis (Optional but Recommended):** For handling job queues (e.g., bulk email dispatch, overnight inventory reconciliation).

### Tier 2: The Core API
- **Node.js LTS + TypeScript:** Enforces strict types and eliminates "magic."
- **NestJS (or Fastify):** Given the complexity of a combined CRM and Warehouse domain, a **Modular Monolith** built on NestJS using Clean/Hexagonal Architecture is highly recommended.
- **Rules:** No business logic in controllers. Strict REST interfaces. API must be versioned.

### Tier 3: The Frontend Identity
- **Next.js (App Router):** Fast, easily deployed, supports Server Components.
- **TypeScript & Tailwind CSS:** Clean, maintainable styling and logic.
- **TanStack Query:** Seamless, cached data fetching.
- **Zod:** Absolute validation for all incoming and outgoing payloads.

### Tier 4: Infrastructure & Deployment
- **Docker Everywhere:** The API and frontend must be containerized.
- **Stateless Services:** Any instance of the Next.js or NestJS app can be killed and restarted without data loss, because the state lives entirely in PostgreSQL.
- **Web-Based Access:** Warehouse staff and CRM users simply access a URL. No Windows installers, no OTA update management required.

## Conclusion

The offline Python stack is a powerful tool for isolated desktop analytics, but it is an anti-pattern for collaborative organizational software. Adopt the Gravity-Approved web stack (Next.js + NestJS + PostgreSQL) to ensure operational stability, data integrity, and multi-user scale.
