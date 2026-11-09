# Kyara installer: private Python 3.11 (via uv) + packages + models.
# Everything is placed inside this folder (.setup\ and runtime\); system Python is not used.
param(
    [switch]$Cpu,          # force CPU build of PyTorch
    [switch]$WithMimic,    # also set up MimicMotion (avatar video)
    [switch]$NoMimic       # never ask about MimicMotion
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # much faster Invoke-WebRequest
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$root = Split-Path -Parent $PSScriptRoot
$setup = Join-Path $root '.setup'
$runtime = Join-Path $root 'runtime'
$python = Join-Path $runtime 'Scripts\python.exe'
New-Item -ItemType Directory -Force -Path $setup | Out-Null

$env:UV_PYTHON_INSTALL_DIR = Join-Path $setup 'python'
$env:UV_CACHE_DIR = Join-Path $setup 'uv-cache'
$env:UV_PYTHON_PREFERENCE = 'only-managed'
$env:UV_NO_CONFIG = '1'
$env:UV_LINK_MODE = 'copy'
$env:PYTHONUTF8 = '1'

function Step($n, $msg) { Write-Host ''; Write-Host "[$n/6] $msg" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)." } }

# ---- 1. uv -------------------------------------------------------------------
Step 1 'Preparing uv (Python package manager)...'
$uv = Join-Path $setup 'uv.exe'
if (!(Test-Path -LiteralPath $uv)) {
    $zip = Join-Path $setup 'uv.zip'
    $url = 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip'
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    $extract = Join-Path $setup 'uv-extract'
    Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force
    $exe = Get-ChildItem -LiteralPath $extract -Filter uv.exe -File -Recurse | Select-Object -First 1
    if (!$exe) { throw 'uv.exe was not found in the downloaded archive.' }
    Copy-Item -LiteralPath $exe.FullName -Destination $uv -Force
    Remove-Item -LiteralPath $zip, $extract -Recurse -Force
}
& $uv --version; Check 'uv'

# ---- 2. Private Python 3.11 + runtime ---------------------------------------
Step 2 'Preparing private Python 3.11 (runtime\)...'
& $uv python install 3.11; Check 'Python install'
if (!(Test-Path -LiteralPath $python)) {
    & $uv venv $runtime --python 3.11 --seed; Check 'runtime creation'
}
& $python --version; Check 'runtime python'

function UvPip { & $uv pip install --python $python @args }

# ---- 3. PyTorch ---------------------------------------------------------------
# Pinned to 2.8: coqui-tts needs torchcodec (+ FFmpeg DLLs) from torch 2.9 on.
$torchPkgs = @('torch==2.8.0', 'torchvision==0.23.0', 'torchaudio==2.8.0')
$hasGpu = $false
if (!$Cpu) { $hasGpu = [bool](Get-Command nvidia-smi -ErrorAction SilentlyContinue) }
if ($hasGpu) {
    Step 3 'NVIDIA GPU detected. Installing PyTorch (CUDA)...'
    UvPip @torchPkgs --index-url https://download.pytorch.org/whl/cu128
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'CUDA 12.8 build failed, trying CUDA 12.6...' -ForegroundColor Yellow
        UvPip @torchPkgs --index-url https://download.pytorch.org/whl/cu126
    }
    if ($LASTEXITCODE -ne 0) { Write-Host 'CUDA build failed. Using CPU build.' -ForegroundColor Yellow; $hasGpu = $false }
}
if (!$hasGpu) {
    Step 3 'Installing PyTorch (CPU)...'
    UvPip @torchPkgs --index-url https://download.pytorch.org/whl/cpu; Check 'PyTorch'
}
& $python -c "import torch; print('torch', torch.__version__, '/ CUDA available:', torch.cuda.is_available())"

# ---- 4. Packages ---------------------------------------------------------------
Step 4 'Installing packages (voice, video, mocap)...'
# requirements-windows.txt uses coqui-tts (the original "TTS" has no Windows wheels).
UvPip -r (Join-Path $root 'requirements-windows.txt'); Check 'Package install'
& $python (Join-Path $root 'patch_tts.py')

# ---- 5. Mocap models -----------------------------------------------------------
Step 5 'Downloading pose estimation models...'
Push-Location $root
& $python -c "import rgb_mocap; [rgb_mocap.ensure_model(m) for m in ('lite','full')]; import cv2, mediapipe; print('mediapipe', mediapipe.__version__, '/ opencv', cv2.__version__)"
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { throw 'Mocap check failed.' }

# ---- 6. MimicMotion (optional) ----------------------------------------------
$mimic = $WithMimic
if (!$WithMimic -and !$NoMimic -and !(Test-Path -LiteralPath (Join-Path $root 'MimicMotion\models\MimicMotion_1-1.pth'))) {
    Write-Host ''
    Write-Host 'Avatar video (MimicMotion) needs an NVIDIA GPU and about 15 GB of downloads.' -ForegroundColor Cyan
    Write-Host 'You can also do this later from the app (Setup tab).'
    $ans = Read-Host 'Set up MimicMotion now? [y/N]'
    $mimic = $ans -match '^[yY]'
}
if ($mimic) {
    Step 6 'Setting up MimicMotion...'
    Push-Location $root
    & $python setup_mimicmotion.py; $c1 = $LASTEXITCODE
    if ($c1 -eq 0) { & $python patch_mimicmotion.py; $c1 = $LASTEXITCODE }
    Pop-Location
    if ($c1 -ne 0) { throw 'MimicMotion setup failed.' }
} else {
    Step 6 'MimicMotion: skipped'
}

Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host ' Install finished!  Start the app with Kyara.cmd' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
exit 0
