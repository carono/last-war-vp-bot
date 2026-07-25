/*
 * unity_ssl_unpin.js — Frida script for Unity/IL2CPP clients on WINDOWS.
 *
 * Purpose: capture TLS PLAINTEXT by hooking BoringSSL's SSL_read / SSL_write
 * (Unity bundles its own BoringSSL, so SSLKEYLOGFILE usually does nothing and a
 * MITM proxy hits certificate pinning). Hooking above the crypto layer sidesteps
 * both problems — you read the bytes the game sends/receives in the clear.
 *
 * This is the NATIVE-Windows variant: it enumerates loaded modules and their
 * exports, NOT the Android/Java layer. No `Java.perform`.
 *
 * ==========================  ACE WARNING  ==================================
 * Frida injects a module and hooks code. Tencent ACE on the OFFICIAL client
 * detects injected modules and debuggers and will crash the game and/or BAN the
 * account. Only run this against a NON-protected build (Android emulator, or a
 * client with ACE disabled) and a THROWAWAY account. Never on server #972.
 * ===========================================================================
 *
 * Usage (WSL can drive a Windows frida via frida-server on Windows, or run
 * frida-tools on Windows directly):
 *
 *   frida -f "C:\\path\\to\\LastWar.exe" -l tools/unity_ssl_unpin.js --runtime=v8
 *   # or attach:
 *   frida -n LastWar.exe -l tools/unity_ssl_unpin.js
 *
 * If SSL_read/SSL_write are not exported (statically linked, symbols stripped),
 * set SSL_READ_OFFSET / SSL_WRITE_OFFSET below to addresses you recovered with
 * Il2CppDumper + IDA/Ghidra (offset from the module base).
 */

'use strict';

// If exports can't be resolved by name, put RVA offsets here (hex strings ok).
// e.g. var SSL_READ_OFFSET = ptr('0x1234560');
var SSL_READ_MODULE = null;      // e.g. 'GameAssembly.dll' — null = search all modules
var SSL_READ_OFFSET = null;
var SSL_WRITE_OFFSET = null;

var MAX_DUMP = 4096;             // cap bytes printed per call

function hexPreview(ptr_, len) {
  try {
    return hexdump(ptr_, { length: Math.min(len, MAX_DUMP), ansi: false });
  } catch (e) {
    return '<unreadable>';
  }
}

// looks-like-protobuf heuristic on the first byte (field<<3 | wiretype2)
function looksProtobuf(ptr_, len) {
  if (len < 1) return false;
  try {
    var b0 = ptr_.readU8();
    return [0x0a, 0x12, 0x1a, 0x22, 0x2a, 0x32, 0x3a, 0x42].indexOf(b0) !== -1;
  } catch (e) { return false; }
}

function findExport(name) {
  // 1) direct global resolution
  var p = Module.findExportByName(null, name);
  if (p) return p;
  // 2) scan every loaded module's exports (BoringSSL may live in a side DLL)
  var found = null;
  Process.enumerateModules().forEach(function (m) {
    if (found) return;
    var e = Module.findExportByName(m.name, name);
    if (e) { found = e; console.log('[ssl] ' + name + ' found in ' + m.name); }
  });
  return found;
}

function resolveByOffset(offset) {
  if (!offset) return null;
  var base;
  if (SSL_READ_MODULE) {
    var m = Process.findModuleByName(SSL_READ_MODULE);
    base = m ? m.base : null;
  } else {
    base = Process.enumerateModules()[0].base; // main exe as a last resort
  }
  return base ? base.add(offset) : null;
}

// SSL_read(SSL *ssl, void *buf, int num)  -> returns bytes read (plaintext IN)
function hookSSLRead(addr) {
  Interceptor.attach(addr, {
    onEnter: function (args) {
      this.buf = args[1];
    },
    onLeave: function (retval) {
      var n = retval.toInt32();
      if (n > 0) {
        var pb = looksProtobuf(this.buf, n) ? ' [protobuf?]' : '';
        console.log('\n<<< SSL_read  ' + n + ' bytes (server->client)' + pb);
        console.log(hexPreview(this.buf, n));
      }
    }
  });
  console.log('[ssl] hooked SSL_read @ ' + addr);
}

// SSL_write(SSL *ssl, const void *buf, int num) (plaintext OUT)
function hookSSLWrite(addr) {
  Interceptor.attach(addr, {
    onEnter: function (args) {
      var buf = args[1];
      var n = args[2].toInt32();
      if (n > 0) {
        var pb = looksProtobuf(buf, n) ? ' [protobuf?]' : '';
        console.log('\n>>> SSL_write ' + n + ' bytes (client->server)' + pb);
        console.log(hexPreview(buf, n));
      }
    }
  });
  console.log('[ssl] hooked SSL_write @ ' + addr);
}

// Optional: neutralise a pin check if you locate one (SSL_CTX_set_verify /
// SSL_set_verify or a custom cert callback). Kept off by default — plaintext
// hooking above is usually enough and less intrusive.
function softenVerify() {
  var setVerify = findExport('SSL_set_verify');
  if (setVerify) {
    Interceptor.attach(setVerify, {
      onEnter: function (args) { args[1] = ptr(0); } // SSL_VERIFY_NONE
    });
    console.log('[ssl] SSL_set_verify forced to SSL_VERIFY_NONE');
  }
}

function main() {
  console.log('[ssl] unity_ssl_unpin — modules loaded: ' + Process.enumerateModules().length);

  var rd = findExport('SSL_read') || resolveByOffset(SSL_READ_OFFSET);
  var wr = findExport('SSL_write') || resolveByOffset(SSL_WRITE_OFFSET);

  if (!rd || !wr) {
    console.log('[ssl] !! could not resolve SSL_read/SSL_write by name.');
    console.log('[ssl]    BoringSSL is likely statically linked & stripped.');
    console.log('[ssl]    Recover the RVAs with Il2CppDumper + IDA/Ghidra and set');
    console.log('[ssl]    SSL_READ_OFFSET / SSL_WRITE_OFFSET (+ SSL_READ_MODULE) at the top.');
  }
  if (rd) hookSSLRead(rd);
  if (wr) hookSSLWrite(wr);
  // softenVerify();  // uncomment only if you actually hit pinning
  console.log('[ssl] ready — interact with the game to see plaintext.');
}

setImmediate(main);
