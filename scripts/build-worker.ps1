# Build video-worker.exe (PyInstaller --onedir)
# Usage: pwsh scripts/build-worker.ps1
# Output: dist/video-worker/video-worker.exe + dist/video-worker/_internal/

$ErrorActionPreference = "Stop"

# 解析项目根目录（脚本在 scripts/ 下，根在上一级）
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location $ProjectRoot

Write-Host "=== PyInstaller 构建 video-worker ===" -ForegroundColor Cyan
Write-Host "项目根目录: $ProjectRoot"

# 清理旧产物
if (Test-Path "dist\video-worker") {
    Write-Host "清理旧 dist\video-worker ..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force "dist\video-worker"
}
if (Test-Path "build") {
    Remove-Item -Recurse -Force "build"
}
if (Test-Path "video-worker.spec") {
    Remove-Item -Force "video-worker.spec"
}

# 准备打包资源
if (-not (Test-Path "tools\ffmpeg.exe")) {
    Write-Error "tools\ffmpeg.exe 不存在，请先放好"
    exit 1
}
if (-not (Test-Path "configs\default.yaml")) {
    Write-Error "configs\default.yaml 不存在"
    exit 1
}

# PyInstaller 调用
# --onedir: 启动快（缓存解压），AV 误报率低
# --add-data "src;dst"：把 configs/、tools/ffmpeg.exe 打进去
# --collect-data pydantic：pydantic v2 schema 数据
# --hidden-import providers：动态 import，PyInstaller 静态分析扫不到
# --exclude-module：requirements.txt 里有但 worker 实际不用的库（librosa 只 legacy 用）
$Args = @(
    "--noconfirm",
    "--clean",
    "--onedir",
    "--name", "video-worker",
    "--console",                           # 保留 stdout（Electron 要 tail）
    "--add-data", "configs;configs",
    "--add-data", "tools\ffmpeg.exe;tools",
    "--hidden-import", "video_worker.providers.qwen_vl",
    "--hidden-import", "video_worker.providers.doubao",
    "--hidden-import", "video_worker.providers.glm",
    "--hidden-import", "video_worker.providers.zai_provider",
    "--collect-data", "pydantic",
    # 排除 worker 实际不用的大块头
    "--exclude-module", "librosa",
    "--exclude-module", "numba",
    "--exclude-module", "llvmlite",
    "--exclude-module", "soundfile",
    "--exclude-module", "torch",
    "--exclude-module", "torchvision",
    "--exclude-module", "torchaudio",
    "--exclude-module", "onnxruntime",
    "--exclude-module", "yt_dlp",
    "--exclude-module", "pandas",
    "--exclude-module", "pyarrow",
    "--exclude-module", "av",
    "--exclude-module", "matplotlib",
    "--exclude-module", "IPython",
    "--exclude-module", "notebook",
    "--exclude-module", "jupyter",
    "--exclude-module", "tqdm",
    "--exclude-module", "rich",
    "--exclude-module", "markdown",
    "--exclude-module", "pypdf",
    "worker_launcher.py"
)

Write-Host "调用 PyInstaller ..." -ForegroundColor Cyan
& pyinstaller @Args
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller 失败 (exit=$LASTEXITCODE)"
    exit $LASTEXITCODE
}

# 校验产物
$ExePath = "dist\video-worker\video-worker.exe"
if (-not (Test-Path $ExePath)) {
    Write-Error "未生成 $ExePath"
    exit 1
}

$ExeSize = [math]::Round((Get-Item $ExePath).Length / 1MB, 1)
$DirSize = [math]::Round((Get-ChildItem "dist\video-worker" -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
Write-Host ""
Write-Host "=== 构建成功 ===" -ForegroundColor Green
Write-Host "video-worker.exe: $ExeSize MB"
Write-Host "整个目录: $DirSize MB"
Write-Host "位置: $((Resolve-Path $ExePath).Path)"
Write-Host ""
Write-Host "测试运行:" -ForegroundColor Cyan
Write-Host "  dist\video-worker\video-worker.exe --help"
Write-Host "  dist\video-worker\video-worker.exe run --skip-vision -i samples\dunhuang -d 15 --work-root test-jobs --skip-auth"
