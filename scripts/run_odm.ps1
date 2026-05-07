$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$dataDir = Join-Path $projectRoot "data"
$projectName = "sfm"
$imagesDir = Join-Path $dataDir "$projectName\images"
$orthophotoPath = Join-Path $dataDir "$projectName\odm_orthophoto\odm_orthophoto.tif"
$dsmPath = Join-Path $dataDir "$projectName\odm_dem\dsm.tif"
$pointCloudPath = Join-Path $dataDir "$projectName\odm_georeferenced_model\odm_georeferenced_model.laz"

if (-not (Test-Path $imagesDir)) {
    Write-Error @"
Error: $imagesDir does not exist.
Copy or symlink your DJI .JPG files there first:
    New-Item -ItemType Directory -Force -Path $imagesDir
    Copy-Item data\raw\*.JPG $imagesDir
"@
}

$dockerRunArgs = @("run")
if ([Console]::IsInputRedirected -or [Console]::IsOutputRedirected -or [Console]::IsErrorRedirected) {
    $dockerRunArgs += "-i"
} else {
    $dockerRunArgs += "-ti"
}
$dockerRunArgs += @(
    "--rm",
    "-v", "${PWD}/data:/datasets",
    "opendronemap/odm",
    "--project-path", "/datasets", $projectName,
    "--orthophoto-resolution", "2",
    "--dsm",
    "--pc-las",
    "--feature-quality", "high",
    "--use-exif"
)

docker @dockerRunArgs
$dockerExitCode = $LASTEXITCODE

Write-Host ""
Write-Host "ODM run summary:"
Write-Host "  Docker exit code: $dockerExitCode"

$expectedOutputs = @(
    @{ Label = "Orthomosaic"; Path = $orthophotoPath },
    @{ Label = "DSM"; Path = $dsmPath },
    @{ Label = "Point cloud"; Path = $pointCloudPath }
)

$missingOutputs = @()
foreach ($output in $expectedOutputs) {
    $exists = Test-Path $output.Path
    if ($exists) {
        Write-Host "  [OK] $($output.Label): $($output.Path)" -ForegroundColor Green
    } else {
        Write-Host "  [X]  $($output.Label): $($output.Path)" -ForegroundColor Red
        $missingOutputs += $output
    }
}

if ($dockerExitCode -ne 0 -or $missingOutputs.Count -gt 0) {
    if ($missingOutputs.Count -gt 0) {
        Write-Error "ODM did not produce all expected deliverables."
    } else {
        Write-Error "ODM exited with a non-zero Docker exit code."
    }
    exit 1
}

Write-Host ""
Write-Host "Done. Key outputs:"
Write-Host "  $orthophotoPath"
Write-Host "  $dsmPath"
Write-Host "  $pointCloudPath"
