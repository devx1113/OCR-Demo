-- CreateTable
CREATE TABLE "projects" (
    "id" VARCHAR(12) NOT NULL,
    "quote_no" VARCHAR(20) NOT NULL,
    "name" TEXT NOT NULL,
    "customer" TEXT NOT NULL DEFAULT '',
    "owner" TEXT NOT NULL DEFAULT '',
    "due_date" VARCHAR(10),
    "rev" INTEGER NOT NULL DEFAULT 0,
    "modified_by" TEXT NOT NULL DEFAULT '',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "settings" JSONB NOT NULL DEFAULT '{}',
    "field_overrides" JSONB NOT NULL DEFAULT '{}',
    "component_overrides" JSONB NOT NULL DEFAULT '{}',
    "extra_components" JSONB NOT NULL DEFAULT '[]',
    "custom_questions" JSONB NOT NULL DEFAULT '[]',
    "chat" JSONB NOT NULL DEFAULT '[]',
    "approval" JSONB,
    "ai_review" JSONB,
    "analysis" JSONB,
    "analysis_stale" BOOLEAN NOT NULL DEFAULT false,
    "exported_at" TEXT,
    "extra" JSONB NOT NULL DEFAULT '{}',

    CONSTRAINT "projects_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "documents" (
    "id" VARCHAR(12) NOT NULL,
    "project_id" VARCHAR(12) NOT NULL,
    "position" INTEGER NOT NULL DEFAULT 0,
    "filename" TEXT NOT NULL,
    "ext" VARCHAR(10) NOT NULL,
    "size" INTEGER NOT NULL,
    "sha256" VARCHAR(64) NOT NULL,
    "kind" VARCHAR(10) NOT NULL,
    "pages" INTEGER,
    "text_layer" BOOLEAN NOT NULL DEFAULT true,
    "status" VARCHAR(10) NOT NULL,
    "messages" JSONB NOT NULL DEFAULT '[]',
    "role" VARCHAR(12) NOT NULL,
    "received_date" VARCHAR(10),
    "version" TEXT,
    "title" TEXT,
    "doc_no" TEXT,
    "include" BOOLEAN NOT NULL DEFAULT true,
    "uploaded_at" TEXT NOT NULL,
    "uploaded_by" TEXT NOT NULL,
    "blocks" INTEGER,
    "tables" INTEGER,
    "extra" JSONB NOT NULL DEFAULT '{}',

    CONSTRAINT "documents_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "parsed_documents" (
    "document_id" VARCHAR(12) NOT NULL,
    "project_id" VARCHAR(12) NOT NULL,
    "data" JSONB NOT NULL,

    CONSTRAINT "parsed_documents_pkey" PRIMARY KEY ("document_id")
);

-- CreateTable
CREATE TABLE "ai_results" (
    "document_id" VARCHAR(12) NOT NULL,
    "project_id" VARCHAR(12) NOT NULL,
    "kind" VARCHAR(10) NOT NULL DEFAULT 'extract',
    "cache_key" VARCHAR(32) NOT NULL,
    "model" TEXT NOT NULL,
    "data" JSONB NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ai_results_pkey" PRIMARY KEY ("document_id")
);

-- CreateTable
CREATE TABLE "history" (
    "id" SERIAL NOT NULL,
    "project_id" VARCHAR(12) NOT NULL,
    "at" TEXT NOT NULL,
    "user" TEXT NOT NULL,
    "action" TEXT NOT NULL,
    "detail" TEXT NOT NULL DEFAULT '',

    CONSTRAINT "history_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "revisions" (
    "id" SERIAL NOT NULL,
    "project_id" VARCHAR(12) NOT NULL,
    "rev" INTEGER NOT NULL,
    "at" TEXT NOT NULL,
    "approved_by" TEXT NOT NULL,
    "sale_total" INTEGER NOT NULL,
    "data" JSONB NOT NULL,

    CONSTRAINT "revisions_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "users" (
    "name" TEXT NOT NULL,
    "role" TEXT NOT NULL,
    "perms" TEXT[],
    "sort" INTEGER NOT NULL DEFAULT 0,

    CONSTRAINT "users_pkey" PRIMARY KEY ("name")
);

-- CreateTable
CREATE TABLE "master_data" (
    "name" VARCHAR(40) NOT NULL,
    "data" JSONB NOT NULL,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_by" TEXT NOT NULL DEFAULT '',

    CONSTRAINT "master_data_pkey" PRIMARY KEY ("name")
);

-- CreateIndex
CREATE UNIQUE INDEX "projects_quote_no_key" ON "projects"("quote_no");

-- CreateIndex
CREATE INDEX "projects_updated_at_idx" ON "projects"("updated_at");

-- CreateIndex
CREATE INDEX "documents_project_id_idx" ON "documents"("project_id");

-- CreateIndex
CREATE UNIQUE INDEX "documents_project_id_sha256_key" ON "documents"("project_id", "sha256");

-- CreateIndex
CREATE INDEX "parsed_documents_project_id_idx" ON "parsed_documents"("project_id");

-- CreateIndex
CREATE INDEX "ai_results_project_id_idx" ON "ai_results"("project_id");

-- CreateIndex
CREATE INDEX "history_project_id_id_idx" ON "history"("project_id", "id");

-- CreateIndex
CREATE UNIQUE INDEX "revisions_project_id_rev_key" ON "revisions"("project_id", "rev");

-- AddForeignKey
ALTER TABLE "documents" ADD CONSTRAINT "documents_project_id_fkey" FOREIGN KEY ("project_id") REFERENCES "projects"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "history" ADD CONSTRAINT "history_project_id_fkey" FOREIGN KEY ("project_id") REFERENCES "projects"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "revisions" ADD CONSTRAINT "revisions_project_id_fkey" FOREIGN KEY ("project_id") REFERENCES "projects"("id") ON DELETE CASCADE ON UPDATE CASCADE;
