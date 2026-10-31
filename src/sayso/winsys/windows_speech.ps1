# Sayso Windows Speech helper. Uses the System.Speech engine that ships with Windows (no install, no admin).
# Protocol: one WAV path per stdin line; one JSON object per stdout line.
param([string]$Culture = "en-US")
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$info = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() |
    Where-Object { $_.Culture.Name -eq $Culture } | Select-Object -First 1
if (-not $info) { $info = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() | Select-Object -First 1 }
if (-not $info) { [Console]::Out.WriteLine('{"ready":false,"error":"no recognizer installed"}'); exit 2 }
$engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine($info)
$engine.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
[Console]::Out.WriteLine('{"ready":true,"culture":"' + $info.Culture.Name + '"}')
[Console]::Out.Flush()
while ($null -ne ($path = [Console]::In.ReadLine())) {
    try {
        $engine.SetInputToWaveFile($path)
        $parts = New-Object System.Collections.Generic.List[string]
        $conf = New-Object System.Collections.Generic.List[double]
        while ($null -ne ($r = $engine.Recognize())) { $parts.Add($r.Text); $conf.Add($r.Confidence) }
        $engine.SetInputToNull()
        $avg = if ($conf.Count) { ($conf | Measure-Object -Average).Average } else { 0 }
        $obj = @{ text = ($parts -join " "); confidence = $avg }
        [Console]::Out.WriteLine(($obj | ConvertTo-Json -Compress))
    } catch {
        [Console]::Out.WriteLine((@{ error = $_.Exception.Message } | ConvertTo-Json -Compress))
    }
    [Console]::Out.Flush()
}
