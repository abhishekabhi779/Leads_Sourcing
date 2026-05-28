# Run this script as Administrator (right-click PowerShell -> Run as Administrator)
# Installs pgvector v0.8.2 for PostgreSQL 18 on Windows

$src = "$env:TEMP\pgvector_pg18"
$pg  = "C:\Program Files\PostgreSQL\18"

if (-not (Test-Path $src)) {
    Write-Host "Downloading pgvector v0.8.2 for PostgreSQL 18..."
    $zip = "$env:TEMP\pgvector_pg18.zip"
    Invoke-WebRequest -Uri "https://github.com/andreiramani/pgvector_pgsql_windows/releases/download/0.8.2_18.0.2/vector.v0.8.2-pg18.zip" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $src -Force
}

Write-Host "Copying files to PostgreSQL 18..."
Copy-Item "$src\lib\vector.dll"            "$pg\lib\"                       -Force
Copy-Item "$src\share\extension\*"         "$pg\share\extension\"           -Force
Copy-Item "$src\include\server\extension\vector" "$pg\include\server\extension\" -Recurse -Force

Write-Host ""
Write-Host "Done! Verify:"
Write-Host "  DLL     : $(Test-Path "$pg\lib\vector.dll")"
Write-Host "  Control : $(Test-Path "$pg\share\extension\vector.control")"
Write-Host ""
Write-Host "Now run: python setup_pgvector.py"
