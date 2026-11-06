# CAM 3.4 PostgreSQL Bootstrap
$PG_HBA  = "C:\Program Files\PostgreSQL\17\data\pg_hba.conf"
$PG_DATA = "C:\Program Files\PostgreSQL\17\data"
$PG_BIN  = "C:\Program Files\PostgreSQL\17\bin"
$env:PATH = "$PG_BIN;$env:PATH"

# Credentials come from the environment (set in your shell or a secrets manager), never from this file.
$APP_USER = $env:CAM_PG_APP_USER
$APP_PASS = $env:CAM_PG_APP_PASSWORD
$PG_PASS  = $env:CAM_PG_SUPERUSER_PASSWORD
foreach ($name in 'CAM_PG_APP_USER', 'CAM_PG_APP_PASSWORD', 'CAM_PG_SUPERUSER_PASSWORD') {
    if (-not (Get-Item "env:$name" -ErrorAction SilentlyContinue).Value) { throw "Set $name before running this script." }
}
if ($APP_PASS -match "'" -or $PG_PASS -match "'") { throw 'Passwords may not contain a single quote (the bootstrap SQL splices them into literals).' }

$utf8NoBom = New-Object System.Text.UTF8Encoding $false

function Write-HBA($method) {
    $c = "# PostgreSQL Client Authentication`r`n# TYPE  DATABASE        USER            ADDRESS                 METHOD`r`n`r`nlocal   all             all                                     $method`r`nhost    all             all             127.0.0.1/32            $method`r`nhost    all             all             ::1/128                 $method`r`nlocal   replication     all                                     $method`r`nhost    replication     all             127.0.0.1/32            $method`r`nhost    replication     all             ::1/128                 $method`r`n"
    [System.IO.File]::WriteAllText($PG_HBA, $c, $utf8NoBom)
}

Write-Host "=== CAM 3.4 PostgreSQL Setup ===" -ForegroundColor Cyan

Write-HBA "trust"
Write-Host "[1] Auth set to trust"

& "$PG_BIN\pg_ctl.exe" reload -D $PG_DATA | Out-Null
Start-Sleep 3
Write-Host "[2] Config reloaded"

$sql = @"
ALTER USER postgres PASSWORD '$PG_PASS';
DO `$`$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$APP_USER') THEN
    EXECUTE 'CREATE ROLE "' || '$APP_USER' || '" WITH LOGIN PASSWORD ''$APP_PASS'' CREATEDB';
  END IF;
END `$`$;
SELECT 'CREATE DATABASE logic_db_2 OWNER "$APP_USER"' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'logic_db_2') \gexec
SELECT 'CREATE DATABASE file_metadata_db_2 OWNER "$APP_USER"' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'file_metadata_db_2') \gexec
GRANT ALL PRIVILEGES ON DATABASE logic_db_2 TO "$APP_USER";
GRANT ALL PRIVILEGES ON DATABASE file_metadata_db_2 TO "$APP_USER";
SELECT rolname FROM pg_roles WHERE rolname = '$APP_USER';
SELECT datname FROM pg_database WHERE datname IN ('logic_db_2','file_metadata_db_2');
"@

$sql | & "$PG_BIN\psql.exe" -U postgres -h 127.0.0.1 -d postgres
Write-Host "[3] SQL executed"

Write-HBA "scram-sha-256"
Write-Host "[4] Auth restored to scram-sha-256"

& "$PG_BIN\pg_ctl.exe" reload -D $PG_DATA | Out-Null
Start-Sleep 2
Write-Host "[5] Config reloaded"

$env:PGPASSWORD = $APP_PASS
$result = & "$PG_BIN\psql.exe" -U "$APP_USER" -h 127.0.0.1 -d logic_db_2 -c "SELECT current_user;" 2>&1
Write-Host "[6] Verify: $result"

Write-Host "`n=== DONE ===" -ForegroundColor Green
Write-Host "  app user  : $APP_USER (password from CAM_PG_APP_PASSWORD)"
Write-Host "  databases : logic_db_2, file_metadata_db_2"
