#Requires -Version 5.1
<#
PEDAL v0.3 Windows native always-on-top overlay.
No installer, no extra Windows libraries, no MQTT credentials.
Uses your existing authenticated dashboard over its ordinary HTTP(S) port.
Usage: powershell -ExecutionPolicy Bypass -File .\overlay\PedalOverlay.ps1 -Server http://192.168.1.21:30926
Security: use only on a trusted LAN, or configure HTTPS first.
#>
param([string]$Server = 'http://192.168.1.21:30926')
$ErrorActionPreference = 'Stop'
$Server = $Server.TrimEnd('/')
if (-not ($Server -match '^https?://[^/]+$')) { throw 'Server must be a complete http(s) URL without a path.' }
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

# Do not store credentials on disk, in script arguments, or in Windows profiles.
$credential = Get-Credential -UserName 'admin' -Message 'Sign in to your PEDAL dashboard'
if ($null -eq $credential) { return }
$plain = $credential.GetNetworkCredential().Password
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
try {
    $response = Invoke-WebRequest -Uri "$Server/login" -Method POST -UseBasicParsing -WebSession $session `
        -ContentType 'application/x-www-form-urlencoded' -Body @{username=$credential.UserName; password=$plain} -TimeoutSec 5
    if ($response.BaseResponse.ResponseUri.AbsolutePath -eq '/login' -or
        $response.Content -match 'Wrong credentials') { throw 'Invalid dashboard username/password.' }
    $cfg = Invoke-RestMethod -Uri "$Server/api/v1/config" -WebSession $session -TimeoutSec 5
    $device = [uri]::EscapeDataString($cfg.device_id)
} catch {
    [System.Windows.Forms.MessageBox]::Show("PEDAL login failed: $($_.Exception.Message)", 'PEDAL Overlay') | Out-Null
    return
} finally {
    $plain = $null
    $credential = $null
}

$bg = [System.Drawing.ColorTranslator]::FromHtml('#10212a')
$fg = [System.Drawing.ColorTranslator]::FromHtml('#edf9f5')
$mint = [System.Drawing.ColorTranslator]::FromHtml('#66e2bd')
$muted = [System.Drawing.ColorTranslator]::FromHtml('#93abb4')
$form = New-Object System.Windows.Forms.Form
$form.Text = 'PEDAL // Mini Cockpit'
$form.Size = [System.Drawing.Size]::new(295,218)
$form.MinimumSize = $form.Size
$form.MaximumSize = $form.Size
$form.StartPosition = 'Manual'
$form.Location = [System.Drawing.Point]::new(([System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea.Right - 315), 42)
$form.FormBorderStyle = 'FixedToolWindow'
$form.BackColor = $bg
$form.ForeColor = $fg
$form.TopMost = $true
$form.ShowInTaskbar = $true
$form.Opacity = 0.96

function New-Label([string]$txt, [int]$x, [int]$y, [int]$w, [int]$h,
                   [float]$fontSize, [System.Drawing.Color]$color, [bool]$bold=$false) {
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $txt
    $label.Location = [System.Drawing.Point]::new($x,$y)
    $label.Size = [System.Drawing.Size]::new($w,$h)
    $style = if ($bold) { [System.Drawing.FontStyle]::Bold } else { [System.Drawing.FontStyle]::Regular }
    $label.Font = [System.Drawing.Font]::new('Segoe UI',$fontSize,$style)
    $label.ForeColor = $color
    $form.Controls.Add($label)
    return $label
}
$null = New-Label 'PEDAL // LIVE' 14 7 255 17 9 $mint $true
$rpm = New-Label '--' 14 29 143 72 44 $fg $true
$null = New-Label 'RPM' 162 72 60 25 13 $mint $true
$goal = New-Label 'Today: loading...' 15 105 255 22 10 $fg
$sessionLabel = New-Label 'Session: --' 15 129 255 22 10 $fg
$level = New-Label 'Level: --' 15 153 135 22 10 $mint
$status = New-Label 'Connecting...' 151 153 121 22 9 $muted

$counter = 0
$dailyTarget = 2000
$levelNumber = 1
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 2000
$timer.Add_Tick({
    try {
        $s = Invoke-RestMethod -Uri "$Server/api/v1/devices/$device/summary" -WebSession $session -TimeoutSec 3
        $seconds = [math]::Max(0, [int]$s.session_duration_s)
        $rpmValue = if ($null -ne $s.last_event_ms -and
            (([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() - [long]$s.last_event_ms) -lt 6000)) {
                [math]::Round([double]$s.live_rpm)
            } else { 0 }
        $rpm.Text = [string]$rpmValue
        $goal.Text = 'Today: {0:N0} / {1:N0} rev' -f [int]$s.today_revolutions,$dailyTarget
        $sessionLabel.Text = 'Session: {0:00}:{1:00}  //  {2:N0} rev' -f [math]::Floor($seconds/60),($seconds%60),[int]$s.session_revolutions
        $level.Text = "Level $levelNumber"
        $status.Text = '● Connected'
        $status.ForeColor = $mint
        if (($counter++ % 8) -eq 0) {
            $f = Invoke-RestMethod -Uri "$Server/api/v1/devices/$device/features" -WebSession $session -TimeoutSec 3
            $dailyTarget = [int]$f.goals.daily.target
            $levelNumber = [int]$f.rpg.level
        }
    } catch {
        $status.Text = '● Reconnecting'
        $status.ForeColor = [System.Drawing.Color]::Orange
    }
})
$form.Add_FormClosed({$timer.Stop();$timer.Dispose()})
$timer.Start()
[void]$form.ShowDialog()
$form.Dispose()
