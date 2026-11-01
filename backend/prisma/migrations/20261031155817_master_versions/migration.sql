-- CreateTable
CREATE TABLE "master_versions" (
    "id" SERIAL NOT NULL,
    "name" VARCHAR(40) NOT NULL,
    "version" INTEGER NOT NULL,
    "data" JSONB NOT NULL,
    "summary" TEXT NOT NULL DEFAULT '',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_by" TEXT NOT NULL DEFAULT '',

    CONSTRAINT "master_versions_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "master_versions_name_version_key" ON "master_versions"("name", "version");
