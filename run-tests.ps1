<#
.SYNOPSIS
  Runs Lento's tests and prints a pass/fail summary. Read docs/TESTING.md for what each one checks.

.EXAMPLE
  .\run-tests.ps1              # everything: unit, Python, GUI and speed tests (about 5 to 10 minutes)
  .\run-tests.ps1 unit         # the app's logic (seconds)
  .\run-tests.ps1 python       # the converter, library tools and practice analyzer (about a minute)
  .\run-tests.ps1 python -Gpu  # ...including the slow homr tests that use the graphics card
  .\run-tests.ps1 gui          # the browser tests at all four screen sizes (a few minutes)
  .\run-tests.ps1 gui-phone    # the browser tests at phone size only (faster)
  .\run-tests.ps1 gui-watch    # opens a window where you can watch each browser test click through the app
  .\run-tests.ps1 report       # opens the report of the last browser-test run
  .\run-tests.ps1 perf         # the speed budgets (builds the app first)
#>
param(
  [ValidateSet("all", "unit", "python", "gui", "gui-phone", "gui-watch", "report", "perf")]
  [string]$What = "all",
  [switch]$Gpu
)

$root = $PSScriptRoot
$app = Join-Path $root "app"
$python = Join-Path $root ".venv\Scripts\python.exe"
$results = [ordered]@{}

function Step([string]$name, [string]$dir, [scriptblock]$command) {
  Write-Host ""
  Write-Host "=== $name ===" -ForegroundColor Cyan
  Push-Location $dir
  try {
    & $command
    $results[$name] = ($LASTEXITCODE -eq 0)
  } catch {
    Write-Host $_ -ForegroundColor Red
    $results[$name] = $false
  } finally {
    Pop-Location
  }
}

function Ensure-Node {
  if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "Node.js isn't installed. Get the LTS version from https://nodejs.org, then open a new PowerShell window."
  }
  if (-not (Test-Path (Join-Path $app "node_modules"))) {
    Write-Host "First run: installing the app's packages (once)..." -ForegroundColor Yellow
    Push-Location $app; npm ci; Pop-Location
  }
}

function Ensure-Browser {
  # downloads Playwright's Chromium the first time; does nothing once it's there
  Push-Location $app; npx playwright install chromium | Out-Null; Pop-Location
}

function Ensure-Python {
  if (-not (Test-Path $python)) {
    throw "No .venv in $root. Make one with:  uv venv; uv pip install -e "".[dev,practice]"""
  }
  & $python -m pytest --version *> $null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "First run: installing pytest and the test packages into .venv (once)..." -ForegroundColor Yellow
    Push-Location $root; uv pip install -e ".[dev,practice]"; Pop-Location
  }
}

$wantUnit = $What -in @("all", "unit")
$wantPython = $What -in @("all", "python")
$wantGui = $What -in @("all", "gui", "gui-phone", "gui-watch", "report")
$wantPerf = $What -in @("all", "perf")

try {
  if ($wantUnit -or $wantGui -or $wantPerf) { Ensure-Node }
  if ($wantGui -or $wantPerf) { Ensure-Browser }
  if ($wantPython) { Ensure-Python }
} catch {
  Write-Host $_ -ForegroundColor Red
  exit 1
}

if ($wantUnit) { Step "Unit tests (app logic)" $app { npm test } }
if ($wantPython) {
  $marker = if ($Gpu) { "" } else { "not homr_gpu" }
  Step "Python tests (converter, library, analyzer)" $root { if ($marker) { & $python -m pytest -m $marker } else { & $python -m pytest } }
}
switch ($What) {
  "gui-watch" { Push-Location $app; npm run e2e:watch; Pop-Location; exit 0 }
  "report" { Push-Location $app; npm run e2e:report; Pop-Location; exit 0 }
  "gui-phone" { Step "GUI tests (phone size)" $app { npm run e2e:phone } }
  default { if ($wantGui) { Step "GUI tests (phone, phone landscape, tablet, desktop)" $app { npm run e2e } } }
}
if ($wantPerf) { Step "Speed budgets" $app { npm run build; if ($LASTEXITCODE -eq 0) { npm run perf } } }

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
$failed = 0
foreach ($r in $results.GetEnumerator()) {
  if ($r.Value) { Write-Host "  PASS  $($r.Key)" -ForegroundColor Green }
  else { Write-Host "  FAIL  $($r.Key)" -ForegroundColor Red; $failed++ }
}
if ($results.Contains("GUI tests (phone, phone landscape, tablet, desktop)") -or $results.Contains("GUI tests (phone size)")) {
  Write-Host ""
  Write-Host "  GUI report: .\run-tests.ps1 report   (screenshots and a step-by-step replay of anything that failed)"
}
exit $failed
