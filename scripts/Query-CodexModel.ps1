[CmdletBinding()]
param(
    [switch]$Once,
    [switch]$Watch,
    [string]$SettingsPath = (Join-Path $PSScriptRoot 'query-settings.json')
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

function Show-Query([string]$Mode) {
    $script:queryFailed = $false
    $sshArgs = @('-T', '-p', [string]$settings.Port, '-i', $queryKey,
        '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
        '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
        '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2',
        ($settings.User + '@' + $settings.Host), $Mode)
    & $sshExe @sshArgs | ForEach-Object {
        $entry = $_ | ConvertFrom-Json
        if ($entry.error) {
            $script:queryFailed = $true
            Write-Host $entry.error -ForegroundColor Red
        } elseif ($entry.notice) {
            Write-Host '最近没有可显示的 Codex 模型记录，请确认 debug 日志并发送请求后再刷新。' -ForegroundColor Yellow
        } elseif ($entry.time -and $entry.provider -and $entry.model) {
            $localTime = [DateTimeOffset]::Parse($entry.time).ToLocalTime().ToString('MM-dd HH:mm:ss')
            Write-Host ('{0}    {1,-10} {2}' -f $localTime, $entry.provider, $entry.model) -ForegroundColor Cyan
        } else {
            throw '服务器返回了非预期的数据。'
        }
    }
    if ($LASTEXITCODE -ne 0 -or $script:queryFailed) {
        throw '查询失败，请检查网络、SSH 主机指纹和 VPS 服务；不会无限重试。'
    }
}

try {
    if ($Once -and $Watch) { throw '-Once 和 -Watch 不能同时使用。' }
    if (-not (Test-Path -LiteralPath $SettingsPath)) {
        throw '请将 examples/query-settings.example.json 复制为 scripts/query-settings.json 并修改配置。'
    }
    $settings = Get-Content -LiteralPath $SettingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($settings.Host -notmatch '^[A-Za-z0-9][A-Za-z0-9.:-]*$' -or
        $settings.User -notmatch '^[A-Za-z_][A-Za-z0-9_-]*$') {
        throw 'Host 或 User 格式不正确。'
    }
    if ([int]$settings.Port -lt 1 -or [int]$settings.Port -gt 65535) { throw 'Port 必须为 1 到 65535。' }
    if (-not $settings.KeyPath) { throw '请设置 KeyPath。' }
    $queryKey = [Environment]::ExpandEnvironmentVariables([string]$settings.KeyPath)
    if (-not [IO.Path]::IsPathRooted($queryKey)) { $queryKey = Join-Path $PSScriptRoot $queryKey }
    if (-not (Test-Path -LiteralPath $queryKey -PathType Leaf)) { throw '未找到专用查询密钥。' }
    $sshExe = (Get-Command ssh.exe -ErrorAction Stop).Source
    Write-Host 'Codex 网关实际请求模型 · 只读查询'
    Write-Host '时间为本机时区；日志包含路由/尝试记录，不保证每行均成功。'
    Write-Host '同一秒、同一上游和同一模型合并；行数不代表请求次数或计费。'
    Write-Host '模型 ID 不能独立证明上游内部身份；此脚本不查询推理强度或剩余额度。'
    Write-Host ''
    Show-Query 'recent'
    if ($Once) { exit 0 }
    if ($Watch) {
        Write-Host '等待新请求，Ctrl+C 退出。' -ForegroundColor Yellow
        Show-Query 'watch'
        exit 0
    }
    while ($true) {
        $choice = Read-Host 'Enter 刷新 / W 实时 / Q 退出'
        if ($choice -match '^(?i)q$') { break }
        if ($choice -match '^(?i)w$') {
            Show-Query 'watch'
            break
        }
        Show-Query 'recent'
    }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    if (-not $Once -and -not $Watch) { Read-Host '按 Enter 关闭窗口' | Out-Null }
    exit 1
}

