# Lanzador rápido de Dew para Tablet RedMagic Astra (16 GB RAM) en Wi-Fi Local
$ErrorActionPreference = "Stop"
Write-Host "Abriendo puerto 8765 en tu red privada local (si Windows pide permiso, acepta)..." -ForegroundColor Cyan
python "$PSScriptRoot\scripts\launch_redmagic_tablet.py"
