import { defineConfig } from "drizzle-kit";

// drizzle-kit (`devbox run migrate-new <name>`) compares src/db/schema.ts with the migrations in drizzle/ and writes
// the next SQL migration; it needs no database connection.
export default defineConfig({
  dialect: "postgresql",
  schema: "./src/db/schema.ts",
  out: "./drizzle",
});
