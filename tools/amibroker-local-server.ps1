param([string]$ProjectRoot="C:\KawkabatSeherAlarqam",[int]$Port=8080,[string]$Symbol="XAUUSD")
$ErrorActionPreference="Stop"
$publicRoot=[IO.Path]::GetFullPath((Join-Path $ProjectRoot "public"))
$runtimeRoot=Join-Path $ProjectRoot "runtime"; [IO.Directory]::CreateDirectory($runtimeRoot)|Out-Null
$quoteFile=Join-Path $runtimeRoot "ami_live.json"
$homeFile=Join-Path $publicRoot "kawkabat-v481-amibroker-local.html"
$listener=New-Object Net.HttpListener; $listener.Prefixes.Add("http://127.0.0.1:$Port/")
$lastPrice=$null; $sequence=0

function Send-Json($c,[int]$status,$payload){
 $b=[Text.Encoding]::UTF8.GetBytes(($payload|ConvertTo-Json -Depth 8 -Compress))
 $c.Response.StatusCode=$status; $c.Response.ContentType="application/json; charset=utf-8"
 $c.Response.Headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
 $c.Response.ContentLength64=$b.Length; $c.Response.OutputStream.Write($b,0,$b.Length)
}

function Read-Quote {
 if(-not [IO.File]::Exists($quoteFile)){throw "AFL bridge has not created runtime\ami_live.json yet."}
 $data=$null
 for($i=0;$i -lt 3 -and $null -eq $data;$i++){
  try{
   $stream=New-Object IO.FileStream($quoteFile,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
   try{$reader=New-Object IO.StreamReader($stream,[Text.Encoding]::UTF8,$true,1024,$false);$raw=$reader.ReadToEnd()}finally{if($null-ne$reader){$reader.Dispose()}elseif($null-ne$stream){$stream.Dispose()}}
   if(-not[String]::IsNullOrWhiteSpace($raw)){$data=$raw|ConvertFrom-Json}
  }catch{if($i-lt 2){Start-Sleep -Milliseconds 2}}
 }
 if($null -eq $data){throw "AFL quote file is being updated; retry."}
 $price=[double]$data.price
 if([double]::IsNaN($price)-or [double]::IsInfinity($price)-or $price -le 0){throw "AFL returned an invalid price."}
 $age=[int64]([DateTime]::UtcNow-[IO.File]::GetLastWriteTimeUtc($quoteFile)).TotalMilliseconds
 if($age -gt 3000){throw "AFL quote is stale ($age ms). Keep the bridge formula applied."}
 $direction=[string]$data.direction
 if($direction -notin @("UP","DOWN","FLAT")){$direction="FLAT";if($null-ne$script:lastPrice){if($price-gt[double]$script:lastPrice){$direction="UP"}elseif($price-lt[double]$script:lastPrice){$direction="DOWN"}}}
 $previous=$script:lastPrice; $script:lastPrice=$price; $script:sequence++
 [ordered]@{ok=$true;symbol=[string]$data.symbol;price=$price;previousPrice=$previous;direction=$direction;sequence=$script:sequence;observedAt=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds();source="AmiBroker.AFL";sourceAgeMs=$age}
}

function Get-ContentType([string]$p){
 switch([IO.Path]::GetExtension($p).ToLowerInvariant()){
  ".html"{return "text/html; charset=utf-8"}; ".js"{return "application/javascript; charset=utf-8"}; ".css"{return "text/css; charset=utf-8"}
  ".json"{return "application/json; charset=utf-8"}; ".svg"{return "image/svg+xml"}; ".png"{return "image/png"}
  ".jpg"{return "image/jpeg"}; ".jpeg"{return "image/jpeg"}; default{return "application/octet-stream"}
 }
}

function Send-File($c,[string]$file){
 if(-not [IO.File]::Exists($file)){Send-Json $c 404 ([ordered]@{ok=$false;error="NOT_FOUND";requestedFile=$file});return}
 $b=[IO.File]::ReadAllBytes($file); $c.Response.StatusCode=200; $c.Response.ContentType=Get-ContentType $file
 $c.Response.Headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
 $c.Response.ContentLength64=$b.Length; $c.Response.OutputStream.Write($b,0,$b.Length)
}

function Resolve-PublicFile([string]$path){
 if($path -eq "/"){return $homeFile}
 $relative=[Uri]::UnescapeDataString($path.TrimStart([char]'/'))
 $candidate=[IO.Path]::GetFullPath((Join-Path $publicRoot $relative))
 $safePrefix=$publicRoot.TrimEnd([IO.Path]::DirectorySeparatorChar)+[IO.Path]::DirectorySeparatorChar
 if(-not $candidate.StartsWith($safePrefix,[StringComparison]::OrdinalIgnoreCase)){return $null}
 return $candidate
}

try{
 if(-not[IO.Directory]::Exists($publicRoot)){throw "Public directory not found: $publicRoot"}
 if(-not[IO.File]::Exists($homeFile)){throw "Wheel home file not found: $homeFile"}
 $listener.Start(); Write-Host "Kawkabat AFL service is running."; Write-Host "Project: $ProjectRoot"; Write-Host "Home file: $homeFile"
 Write-Host "Wheel: http://127.0.0.1:$Port/"; Write-Host "Quote: http://127.0.0.1:$Port/api/quote"; Write-Host "Waiting for: $quoteFile"
 while($listener.IsListening){
  $c=$listener.GetContext()
  try{
   $p=$c.Request.Url.AbsolutePath
   if($p-eq"/api/health"){Send-Json $c 200 ([ordered]@{ok=$true;service="kawkabat-amibroker-afl";symbol=$Symbol;source="AmiBroker.AFL"})}
   elseif($p-eq"/api/quote"){try{Send-Json $c 200 (Read-Quote)}catch{Send-Json $c 503 ([ordered]@{ok=$false;symbol=$Symbol;error="AFL_QUOTE_UNAVAILABLE";message=$_.Exception.Message})}}
   else{$file=Resolve-PublicFile $p;if($null-eq$file){Send-Json $c 403 ([ordered]@{ok=$false;error="FORBIDDEN"})}else{Send-File $c $file}}
  }finally{try{$c.Response.OutputStream.Close()}catch{}}
 }
}finally{try{$listener.Stop();$listener.Close()}catch{}}
