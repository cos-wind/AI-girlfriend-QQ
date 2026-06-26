$ErrorActionPreference = "SilentlyContinue"

$ProjectDir = Split-Path -Parent $PSScriptRoot
$StickerRoot = Join-Path $ProjectDir "data\stickers\_online_default"
$BaseUrl = "https://raw.githubusercontent.com/googlefonts/noto-emoji/main/png/128"

$items = @(
    @{ emotion = "happy"; codes = @("1f60a", "1f389") },
    @{ emotion = "comfort"; codes = @("1f917", "1f49b") },
    @{ emotion = "tired"; codes = @("1f634", "1f62a") },
    @{ emotion = "proud"; codes = @("1f60e", "1f3c6") },
    @{ emotion = "confused"; codes = @("1f914", "1f644") },
    @{ emotion = "shy"; codes = @("1f633", "1f970") },
    @{ emotion = "food"; codes = @("1f35c", "1f371") },
    @{ emotion = "goodnight"; codes = @("1f319", "1f4a4") },
    @{ emotion = "pout"; codes = @("1f621", "1f624") }
)

New-Item -ItemType Directory -Force -Path $StickerRoot | Out-Null

foreach ($item in $items) {
    $dir = Join-Path $StickerRoot $item.emotion
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    foreach ($code in $item.codes) {
        $url = "$BaseUrl/emoji_u$code.png"
        $target = Join-Path $dir "noto_$code.png"
        if (Test-Path -LiteralPath $target) {
            continue
        }
        try {
            Invoke-WebRequest -Uri $url -OutFile $target -UseBasicParsing -TimeoutSec 30
            Write-Host "Downloaded $target"
        } catch {
            Write-Host "Failed $url"
        }
    }
}

$notice = @"
Default online sticker seed
Source: Google Noto Emoji
Repository: https://github.com/googlefonts/noto-emoji
License: Apache License 2.0

These images are cached locally so the bot does not need to fetch the network while chatting.
Manual stickers can be added to data/stickers/<emotion>/.
Chat-history stickers are saved to data/stickers/_chat_history/<emotion>/.
"@

Set-Content -LiteralPath (Join-Path $StickerRoot "ATTRIBUTION.txt") -Value $notice -Encoding UTF8
