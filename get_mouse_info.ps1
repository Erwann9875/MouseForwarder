$rows = Get-PnpDevice -Class Mouse -PresentOnly | ForEach-Object {
  $cid = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName 'DEVPKEY_Device_ContainerId' -ErrorAction SilentlyContinue).Data
  $bus = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName 'DEVPKEY_Device_BusReportedDeviceDesc' -ErrorAction SilentlyContinue).Data
  $svc = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName 'DEVPKEY_Device_Service' -ErrorAction SilentlyContinue).Data
  $compat = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName 'DEVPKEY_Device_CompatibleIds' -ErrorAction SilentlyContinue).Data

  $vid = [Regex]::Match($_.InstanceId,'VID_([0-9A-F]{4})').Groups[1].Value
  $pidH = [Regex]::Match($_.InstanceId,'PID_([0-9A-F]{4})').Groups[1].Value

  $score = 0
  if ($bus -match '(?i)\b(mouse|souris)\b') { $score += 3 }
  if ($bus -match '(?i)\b(keyboard|clavier)\b') { $score -= 3 }
  if ($compat -contains 'HID_DEVICE_SYSTEM_MOUSE' -or ($compat | Where-Object { $_ -match 'HID_DEVICE_UP:0001_U:0002' })) { $score += 2 }
  if ($svc -eq 'mouhid') { $score += 1 }

  [pscustomobject]@{ Product=$bus; VID=$vid; PID=$pidH; InstanceId=$_.InstanceId; ContainerId=$cid; Score=$score }
}

$bestPerDevice = $rows |
  Group-Object ContainerId |
  ForEach-Object { $_.Group | Sort-Object Score -Descending | Select-Object -First 1 }

$mouse = $bestPerDevice | Where-Object { $_.Score -ge 1 } | Sort-Object Score -Descending | Select-Object -First 1
if (-not $mouse) { Write-Error "Aucune souris trouvée"; exit 1 }

$serial = ($mouse.InstanceId -split '\\')[-1]
[pscustomobject]@{ VID = $mouse.VID; PID = $mouse.PID; Serial = $serial } | ConvertTo-Json -Compress
