# Reach a running MACS+ instance's DOM from another process.
#
# MACS+.exe is a launcher: it starts <install>\Support\Entry.hta under
# SysWOW64\mshta.exe and exits, so the application window belongs to mshta and
# enumerating by MACS+.exe's PID finds nothing.
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class Dom {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr p, EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int m);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int m);
  [DllImport("user32.dll", CharSet=CharSet.Auto)] public static extern uint RegisterWindowMessage(string s);
  [DllImport("user32.dll")] public static extern IntPtr SendMessageTimeout(IntPtr h, uint msg, IntPtr wp, IntPtr lp, uint flags, uint timeout, out IntPtr result);
  [DllImport("oleacc.dll", PreserveSig=false)]
  public static extern void ObjectFromLresult(IntPtr lResult, ref Guid riid, IntPtr wParam,
      [MarshalAs(UnmanagedType.IUnknown)] out object ppvObject);
  public static string Cls(IntPtr h){ var sb=new StringBuilder(256); GetClassName(h,sb,256); return sb.ToString(); }
  public static string Txt(IntPtr h){ var sb=new StringBuilder(512); GetWindowText(h,sb,512); return sb.ToString(); }
}
"@

function Get-IEServerHwnd([string]$titleMatch) {
  $frame = [IntPtr]::Zero
  $cb = [Dom+EnumProc]{ param($h,$l)
    if ([Dom]::Cls($h) -eq 'HTML Application Host Window Class' -and [Dom]::Txt($h) -match $titleMatch) {
      $script:frame = $h
    }
    return $true }
  [Dom]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
  if ($script:frame -eq [IntPtr]::Zero) { throw "HTA frame window not found" }
  $script:ie = [IntPtr]::Zero
  $walk = $null
  $walk = { param($p)
    $cb2 = [Dom+EnumProc]{ param($c,$l)
      if ([Dom]::Cls($c) -eq 'Internet Explorer_Server' -and $script:ie -eq [IntPtr]::Zero) { $script:ie = $c }
      & $walk $c
      return $true }
    [Dom]::EnumChildWindows($p, $cb2, [IntPtr]::Zero) | Out-Null }
  & $walk $script:frame
  if ($script:ie -eq [IntPtr]::Zero) { throw "Internet Explorer_Server child not found" }
  return @{ Frame = $script:frame; IE = $script:ie }
}

function Get-Document([IntPtr]$ieHwnd) {
  $msg = [Dom]::RegisterWindowMessage("WM_HTML_GETOBJECT")
  $res = [IntPtr]::Zero
  [Dom]::SendMessageTimeout($ieHwnd, $msg, [IntPtr]::Zero, [IntPtr]::Zero, 2, 5000, [ref]$res) | Out-Null
  if ($res -eq [IntPtr]::Zero) { throw "WM_HTML_GETOBJECT returned 0" }
  $iid = [Guid]"332C4425-26CB-11D0-B483-00C04FD90119"   # IHTMLDocument2
  $obj = $null
  [Dom]::ObjectFromLresult($res, [ref]$iid, [IntPtr]::Zero, [ref]$obj)
  return $obj
}
