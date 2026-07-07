param(
    [switch]$Launch
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$GuiLauncher = Join-Path $ProjectRoot ".venv\Scripts\atri-desktop-pet.exe"
$IconPath = Join-Path $ProjectRoot "src\atri_desktop\assets\atri-desktop-pet.ico"
$IconSource = Join-Path $ProjectRoot "src\atri_desktop\assets\expressions\snack.png"

$ProgramsDir = [Environment]::GetFolderPath("Programs")
$DesktopDir = [Environment]::GetFolderPath("Desktop")
$StartMenuDir = Join-Path $ProgramsDir "Atri QQ Bot"
$ShortcutName = [string]::Concat([char]0x4E9A, [char]0x6258, [char]0x8389, [char]0x684C, [char]0x5BA0, ".lnk")
$StartMenuShortcut = Join-Path $StartMenuDir $ShortcutName
$DesktopShortcut = Join-Path $DesktopDir $ShortcutName
$Description = [string]::Concat([char]0x4E9A, [char]0x6258, [char]0x8389, [char]0x684C, [char]0x5BA0, " - desktop pet only")
$AppUserModelId = "AtriQQBot.DesktopPet"

function Set-ShortcutAppUserModelId {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$AppId
    )

    $typeName = "AtriDesktopPet.ShortcutAppUserModelId"
    if (-not ($typeName -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

namespace AtriDesktopPet
{
    [ComImport]
    [Guid("00021401-0000-0000-C000-000000000046")]
    internal class ShellLink
    {
    }

    [ComImport]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    [Guid("0000010b-0000-0000-C000-000000000046")]
    internal interface IPersistFile
    {
        void GetClassID(out Guid pClassID);
        void IsDirty();
        void Load([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, uint dwMode);
        void Save([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, bool fRemember);
        void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string pszFileName);
        void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string ppszFileName);
    }

    [ComImport]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    [Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
    internal interface IPropertyStore
    {
        void GetCount(out uint cProps);
        void GetAt(uint iProp, out PropertyKey pkey);
        void GetValue(ref PropertyKey key, out PropVariant pv);
        void SetValue(ref PropertyKey key, ref PropVariant pv);
        void Commit();
    }

    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    internal struct PropertyKey
    {
        public Guid fmtid;
        public uint pid;

        public PropertyKey(Guid fmtid, uint pid)
        {
            this.fmtid = fmtid;
            this.pid = pid;
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct PropVariant : IDisposable
    {
        public ushort vt;
        public ushort reserved1;
        public ushort reserved2;
        public ushort reserved3;
        public IntPtr pointerValue;

        public static PropVariant FromString(string value)
        {
            return new PropVariant
            {
                vt = 31,
                pointerValue = Marshal.StringToCoTaskMemUni(value)
            };
        }

        public void Dispose()
        {
            if (pointerValue != IntPtr.Zero)
            {
                Marshal.FreeCoTaskMem(pointerValue);
                pointerValue = IntPtr.Zero;
            }
        }
    }

    public static class ShortcutAppUserModelId
    {
        public static void Set(string shortcutPath, string appId)
        {
            var link = new ShellLink();
            var persistFile = (IPersistFile)link;
            persistFile.Load(shortcutPath, 2);

            var propertyStore = (IPropertyStore)link;
            var appIdKey = new PropertyKey(new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5);
            var value = PropVariant.FromString(appId);
            try
            {
                propertyStore.SetValue(ref appIdKey, ref value);
                propertyStore.Commit();
                persistFile.Save(shortcutPath, true);
            }
            finally
            {
                value.Dispose();
            }
        }
    }
}
"@
    }

    [AtriDesktopPet.ShortcutAppUserModelId]::Set($Path, $AppId)
}

function Ensure-DesktopPetLauncher {
    $python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        $pythonCommand = "python"
        if (Get-Command py -ErrorAction SilentlyContinue) {
            $pythonCommand = "py -3"
        }
        Invoke-Expression "$pythonCommand -m venv `"$ProjectRoot\.venv`""
    }

    $python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    & $python -m pip install -e $ProjectRoot --disable-pip-version-check | Out-Null
    if ($LASTEXITCODE -ne 0 -and (Test-Path -LiteralPath $GuiLauncher)) {
        Write-Warning "Could not refresh GUI launcher; it may be running. Reusing existing launcher: $GuiLauncher"
        return
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $GuiLauncher)) {
        throw "Failed to create desktop pet GUI launcher: $GuiLauncher"
    }
}

function Ensure-DesktopPetIcon {
    if (-not (Test-Path -LiteralPath $IconSource)) {
        throw "Desktop pet icon source was not found: $IconSource"
    }

    $python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        $python = "python"
        if (Get-Command py -ErrorAction SilentlyContinue) {
            $python = "py"
        }
    }

    $script = @"
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

source = Path(r"$IconSource")
out = Path(r"$IconPath")
out.parent.mkdir(parents=True, exist_ok=True)
base = Image.open(source).convert("RGBA")
# The expression sprites include decorative padding. A fixed crop keeps the
# shortcut icon centered and avoids a pale empty lower half.
base = base.crop((8, 0, 89, 94))
sizes = [256, 128, 96, 64, 48, 32, 24, 16]
frames = []
for size in sizes:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_margin = max(1, round(size * 0.075))
    shadow_draw.ellipse(
        [shadow_margin, shadow_margin + max(1, size // 64), size - shadow_margin - 1, size - shadow_margin - 1],
        fill=(58, 42, 56, 58),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, size // 48)))
    canvas.alpha_composite(shadow)
    draw = ImageDraw.Draw(canvas)
    margin = max(1, round(size * 0.06))
    ellipse = [margin, margin, size - margin - 1, size - margin - 1]
    draw.ellipse(ellipse, fill=(255, 247, 223, 255), outline=(91, 64, 83, 238), width=max(1, size // 22))
    inset = max(1, round(size * 0.105))
    draw.arc([inset, inset, size - inset - 1, size - inset - 1], 215, 325, fill=(234, 177, 157, 210), width=max(1, size // 42))
    pet = base.copy()
    max_width = round(size * 0.62)
    max_height = round(size * 0.64)
    ratio = min(max_width / pet.width, max_height / pet.height)
    pet = pet.resize((round(pet.width * ratio), round(pet.height * ratio)), Image.Resampling.LANCZOS)
    x = (size - pet.width) // 2
    y = (size - pet.height) // 2 + round(size * 0.05)
    canvas.alpha_composite(pet, (x, y))
    frames.append(canvas)
frames[0].save(out, sizes=[(s, s) for s in sizes])
"@
    $script | & $python -
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $IconPath)) {
        throw "Failed to create desktop pet icon: $IconPath"
    }
}

function New-DesktopPetShortcut {
    param(
        [Parameter(Mandatory=$true)][string]$Path
    )

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    if (-not (Test-Path -LiteralPath $GuiLauncher)) {
        throw "Desktop pet GUI launcher was not found: $GuiLauncher"
    }
    $shortcut.TargetPath = $GuiLauncher
    $shortcut.Arguments = ""
    $shortcut.WorkingDirectory = $ProjectRoot
    $shortcut.Description = $Description
    if (Test-Path -LiteralPath $IconPath) {
        $shortcut.IconLocation = $IconPath
    }
    $shortcut.Save()
    try {
        Set-ShortcutAppUserModelId -Path $Path -AppId $AppUserModelId
    } catch {
        Write-Warning ("Could not set shortcut AppUserModelID: " + $_.Exception.Message)
    }
}

Ensure-DesktopPetIcon
Ensure-DesktopPetLauncher
New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null

New-DesktopPetShortcut -Path $StartMenuShortcut
New-DesktopPetShortcut -Path $DesktopShortcut

Write-Host ("Start menu shortcut created: " + $StartMenuShortcut)
Write-Host ("Desktop shortcut created: " + $DesktopShortcut)

if ($Launch) {
    if (-not (Test-Path -LiteralPath $GuiLauncher)) {
        throw "Desktop pet GUI launcher was not found: $GuiLauncher"
    }
    Start-Process -FilePath $GuiLauncher -WorkingDirectory $ProjectRoot
    Write-Host "Desktop pet launch command sent."
}
