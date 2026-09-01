$ErrorActionPreference = "Stop"

$javac = Get-Command javac -ErrorAction Stop
$binDirectory = Split-Path -Parent $javac.Source
$javaHome = Split-Path -Parent $binDirectory
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$javaVersion = & (Join-Path $binDirectory "java.exe") -version 2>&1
$ErrorActionPreference = $previousErrorActionPreference
$javaVersionText = $javaVersion -join "`n"

if ($javaVersionText -notmatch 'version "21\.') {
  throw "Java 21 is required, but javac resolves to $($javac.Source)"
}

$env:JAVA_HOME = $javaHome
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
  & mvn @args
  $mavenExitCode = $LASTEXITCODE
} finally {
  Pop-Location
}
exit $mavenExitCode
