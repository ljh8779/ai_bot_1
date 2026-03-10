param(
    [string]$OutputDir = "tmp\db_migration",
    [string]$DumpBaseName = "local-rag-db"
)

$ErrorActionPreference = "Stop"

function Get-EnvValue {
    param(
        [string]$Path,
        [string]$Key
    )

    $line = Select-String -Path $Path -Pattern "^$Key=" | Select-Object -Last 1
    if (-not $line) {
        return $null
    }
    return ($line.Line -split "=", 2)[1]
}

function Require-Value {
    param(
        [string]$Name,
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "$Name is missing."
    }
}

$rootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$envPath = Join-Path $rootDir ".env"

if (-not (Test-Path $envPath)) {
    throw ".env not found at $envPath"
}

$databaseUrl = Get-EnvValue -Path $envPath -Key "DATABASE_URL"
$embeddingDimensions = Get-EnvValue -Path $envPath -Key "EMBEDDING_DIMENSIONS"
$llmProvider = Get-EnvValue -Path $envPath -Key "LLM_PROVIDER"
$googleEmbeddingModel = Get-EnvValue -Path $envPath -Key "GOOGLE_EMBEDDING_MODEL"
$hfEmbeddingModel = Get-EnvValue -Path $envPath -Key "HF_EMBEDDING_MODEL"

Require-Value -Name "DATABASE_URL" -Value $databaseUrl
Require-Value -Name "EMBEDDING_DIMENSIONS" -Value $embeddingDimensions

$match = [regex]::Match($databaseUrl, "^postgresql\+psycopg://(?<user>[^:]+):(?<password>[^@]+)@(?<host>[^:\/]+):(?<port>\d+)\/(?<db>.+)$")
if (-not $match.Success) {
    throw "DATABASE_URL format is not supported: $databaseUrl"
}

$dbUser = $match.Groups["user"].Value
$dbPassword = $match.Groups["password"].Value
$dbName = $match.Groups["db"].Value
$containerName = "rag_db"

$runningContainers = docker ps --format "{{.Names}}"
if (-not ($runningContainers -split "`n" | Where-Object { $_ -eq $containerName })) {
    throw "Docker container '$containerName' is not running."
}

$outputRoot = Join-Path $rootDir $OutputDir
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$dumpFile = Join-Path $outputRoot "$DumpBaseName-$timestamp.dump"
$metaFile = Join-Path $outputRoot "$DumpBaseName-$timestamp.metadata.env"
$containerDump = "/tmp/$DumpBaseName-$timestamp.dump"

Write-Host "[1/4] Exporting local database from container '$containerName'..."
docker exec -e "PGPASSWORD=$dbPassword" $containerName pg_dump -U $dbUser -d $dbName -Fc -f $containerDump | Out-Null

Write-Host "[2/4] Copying dump to $dumpFile ..."
docker cp "${containerName}:$containerDump" $dumpFile | Out-Null
docker exec $containerName rm -f $containerDump | Out-Null

Write-Host "[3/4] Collecting metadata ..."
$stats = docker exec -e "PGPASSWORD=$dbPassword" $containerName `
    psql -U $dbUser -d $dbName -t -A -F "|" -c `
    "select (select count(*) from documents), (select count(*) from document_chunks), (select format_type(atttypid, atttypmod) from pg_attribute where attrelid = 'document_chunks'::regclass and attname = 'embedding');"

$parts = $stats.Trim().Split("|")
if ($parts.Length -ne 3) {
    throw "Unexpected stats output: $stats"
}

$documentCount = $parts[0]
$chunkCount = $parts[1]
$embeddingType = $parts[2]

$metaLines = @(
    "EXPORTED_AT=$timestamp",
    "SOURCE_CONTAINER=$containerName",
    "SOURCE_DB_NAME=$dbName",
    "SOURCE_DB_USER=$dbUser",
    "SOURCE_DOCUMENT_COUNT=$documentCount",
    "SOURCE_CHUNK_COUNT=$chunkCount",
    "SOURCE_EMBEDDING_TYPE=$embeddingType",
    "EXPECTED_EMBEDDING_DIMENSIONS=$embeddingDimensions",
    "LLM_PROVIDER=$llmProvider",
    "GOOGLE_EMBEDDING_MODEL=$googleEmbeddingModel",
    "HF_EMBEDDING_MODEL=$hfEmbeddingModel"
)
Set-Content -Path $metaFile -Value $metaLines

Write-Host "[4/4] Done."
Write-Host "Dump: $dumpFile"
Write-Host "Metadata: $metaFile"
Write-Host "Documents: $documentCount"
Write-Host "Chunks: $chunkCount"
Write-Host "Embedding: $embeddingType"
