param([Parameter(Mandatory=$true)][string]$InputJson)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$cfg=Get-Content -LiteralPath $InputJson -Raw | ConvertFrom-Json
$source=$null;$bitmap=$null;$graphics=$null;$stream=$null;$software=$null
try {
    $source=[System.Drawing.Image]::FromFile($cfg.source)
    if ($source.Width*$source.Height -gt 16000000) { throw 'Image exceeds 16 megapixels.' }
    $crop=$cfg.crop
    $region=[System.Drawing.RectangleF]::new([single]($source.Width*$crop.x),[single]($source.Height*$crop.y),[single]($source.Width*$crop.width),[single]($source.Height*$crop.height))
    $scale=[Math]::Min(1,[Math]::Min(1600/$region.Width,1600/$region.Height))
    $w=[Math]::Max(1,[int]($region.Width*$scale));$h=[Math]::Max(1,[int]($region.Height*$scale))
    $bitmap=[System.Drawing.Bitmap]::new($w,$h)
    $graphics=[System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.Clear([System.Drawing.Color]::FromArgb(9,9,14))
    $graphics.DrawImage($source,[System.Drawing.RectangleF]::new(0,0,$w,$h),$region,[System.Drawing.GraphicsUnit]::Pixel)
    $graphics.Dispose();$graphics=$null;$source.Dispose();$source=$null
    $bitmap.Save($cfg.ocr_input,[System.Drawing.Imaging.ImageFormat]::Png)
    $null=[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
    $null=[Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime]
    $null=[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
    $asTask=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
    function Await($operation,[Type]$resultType) {
        $task=$asTask.MakeGenericMethod($resultType).Invoke($null,@($operation))
        if (-not $task.Wait(12000)) { throw 'Local OCR timed out.' }
        return $task.Result
    }
    $file=Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($cfg.ocr_input)) ([Windows.Storage.StorageFile])
    $stream=Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder=Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $software=Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if (-not $engine) { throw 'Install a Windows OCR language before creating a private preview.' }
    $result=Await ($engine.RecognizeAsync($software)) ([Windows.Media.Ocr.OcrResult])
    if ($result.TextAngle -and [Math]::Abs($result.TextAngle) -gt 5) { throw 'Rotate the image upright before creating a private preview.' }
    $boxes=@()
    foreach ($line in $result.Lines) { foreach ($word in $line.Words) {
        $r=$word.BoundingRect
        $x=[Math]::Max(0,[int]$r.X-6);$y=[Math]::Max(0,[int]$r.Y-6)
        $right=[Math]::Min($w,[Math]::Ceiling($r.X+$r.Width)+6);$bottom=[Math]::Min($h,[Math]::Ceiling($r.Y+$r.Height)+6)
        $boxes+=@{x=$x/$w;y=$y/$h;width=($right-$x)/$w;height=($bottom-$y)/$h}
    }}
    $automatic=$boxes.Count
    $all=@($boxes)+@($cfg.masks)
    # Collapse each covered region to one colour: original glyph pixels are absent
    # from the flattened output, rather than hidden behind a reversible SVG filter.
    foreach ($box in $all) {
        $rect=[System.Drawing.Rectangle]::new([int]($box.x*$w),[int]($box.y*$h),[Math]::Max(1,[int][Math]::Ceiling($box.width*$w)),[Math]::Max(1,[int][Math]::Ceiling($box.height*$h)))
        $rect.Intersect([System.Drawing.Rectangle]::new(0,0,$w,$h))
        if ($rect.Width -lt 1 -or $rect.Height -lt 1) { continue }
        $pixel=[System.Drawing.Bitmap]::new(1,1);$pg=[System.Drawing.Graphics]::FromImage($pixel)
        $pg.DrawImage($bitmap,[System.Drawing.Rectangle]::new(0,0,1,1),$rect,[System.Drawing.GraphicsUnit]::Pixel)
        $brush=[System.Drawing.SolidBrush]::new($pixel.GetPixel(0,0));$g=[System.Drawing.Graphics]::FromImage($bitmap)
        $g.FillRectangle($brush,$rect);$g.Dispose();$brush.Dispose();$pg.Dispose();$pixel.Dispose()
    }
    $thumb=[System.Drawing.Bitmap]::new(1280,800);$g=[System.Drawing.Graphics]::FromImage($thumb)
    try {
        $g.Clear([System.Drawing.Color]::FromArgb(9,9,14));$fit=[Math]::Min(1280/$w,800/$h)
        $g.InterpolationMode=[System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $dest=[System.Drawing.RectangleF]::new([single]((1280-$w*$fit)/2),[single]((800-$h*$fit)/2),[single]($w*$fit),[single]($h*$fit))
        $g.DrawImage($bitmap,$dest);$thumb.Save($cfg.output,[System.Drawing.Imaging.ImageFormat]::Png)
    } finally { $g.Dispose();$thumb.Dispose() }
    @{automatic_regions=$automatic;boxes=@($boxes);width=$w;height=$h} | ConvertTo-Json -Depth 6 -Compress
} finally {
    if ($graphics) {$graphics.Dispose()};if ($source) {$source.Dispose()};if ($bitmap) {$bitmap.Dispose()}
    if ($software) {$software.Dispose()};if ($stream) {$stream.Dispose()}
}
