/* LocalBox: import and verify one public CA through the same ROOT API games use.
 * No CRT, registry-file editing, network access, private keys, or Wine certutil.
 * Build: python3 tools/build-trust-helper.py. Licensed under AGPL-3.0-or-later.
 */
typedef unsigned char BYTE;
typedef unsigned long DWORD;
typedef int BOOL;
typedef __WCHAR_TYPE__ WCHAR;
typedef void *HANDLE;
typedef void *HCERTSTORE;
typedef __UINTPTR_TYPE__ ULONG_PTR;
typedef struct CERT_CONTEXT {
    DWORD encoding;
    BYTE *encoded;
    DWORD length;
    void *info;
    HCERTSTORE store;
} CERT_CONTEXT;
typedef const CERT_CONTEXT *PCCERT_CONTEXT;
#define API __declspec(dllimport)
API WCHAR *GetCommandLineW(void);
API WCHAR **CommandLineToArgvW(const WCHAR *, int *);
API HANDLE LocalFree(HANDLE);
API HANDLE CreateFileW(const WCHAR *, DWORD, DWORD, void *, DWORD, DWORD, HANDLE);
API DWORD GetFileSize(HANDLE, DWORD *);
API BOOL ReadFile(HANDLE, void *, DWORD, DWORD *, void *);
API BOOL WriteFile(HANDLE, const void *, DWORD, DWORD *, void *);
API BOOL CloseHandle(HANDLE);
API HANDLE GetStdHandle(DWORD);
API DWORD GetLastError(void);
API __declspec(noreturn) void ExitProcess(DWORD);
API BOOL CryptHashCertificate2(const WCHAR *, DWORD, void *, const BYTE *, DWORD, BYTE *, DWORD *);
API PCCERT_CONTEXT CertCreateCertificateContext(DWORD, const BYTE *, DWORD);
API BOOL CertFreeCertificateContext(PCCERT_CONTEXT);
API HCERTSTORE CertOpenStore(const char *, DWORD, ULONG_PTR, DWORD, const void *);
API HCERTSTORE CertOpenSystemStoreW(ULONG_PTR, const WCHAR *);
API BOOL CertCloseStore(HCERTSTORE, DWORD);
API BOOL CertAddCertificateContextToStore(HCERTSTORE, PCCERT_CONTEXT, DWORD, PCCERT_CONTEXT *);
API PCCERT_CONTEXT CertEnumCertificatesInStore(HCERTSTORE, PCCERT_CONTEXT);

static BYTE file_data[65536];
static void print(const char *text) {
    DWORD n = 0, written;
    while (text[n]) n++;
    WriteFile(GetStdHandle((DWORD)-11), text, n, &written, 0);
}
static int equal(const WCHAR *a, const WCHAR *b) {
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}
static int digit(WCHAR c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}
static int hash_matches(const BYTE *data, DWORD length, const BYTE *expected) {
    BYTE hash[32]; DWORD size = 32, i;
    if (!CryptHashCertificate2(L"SHA256", 0, 0, data, length, hash, &size) || size != 32) return 0;
    for (i = 0; i < 32; i++) if (hash[i] != expected[i]) return 0;
    return 1;
}
static int root_contains(const BYTE *expected) {
    HCERTSTORE root = CertOpenSystemStoreW(0, L"ROOT");
    PCCERT_CONTEXT current = 0;
    int found = 0;
    if (!root) return 0;
    while ((current = CertEnumCertificatesInStore(root, current))) {
        if (hash_matches(current->encoded, current->length, expected)) {
            found = 1;
            CertFreeCertificateContext(current);
            break;
        }
    }
    CertCloseStore(root, 0);
    return found;
}
static DWORD run(int argc, WCHAR **argv) {
    HANDLE file;
    DWORD length, read, i;
    BYTE expected[32];
    PCCERT_CONTEXT certificate;
    HCERTSTORE store;
    if (argc != 4 || (!equal(argv[1], L"install") && !equal(argv[1], L"verify"))) return 10;
    for (i = 0; i < 64; i++) {
        if (!argv[3][i] || digit(argv[3][i]) < 0) return 10;
        if (!(i & 1)) expected[i / 2] = (BYTE)(digit(argv[3][i]) << 4);
        else expected[i / 2] |= (BYTE)digit(argv[3][i]);
    }
    if (argv[3][64]) return 10;
    file = CreateFileW(argv[2], 0x80000000, 1, 0, 3, 0, 0);
    if (file == (HANDLE)(ULONG_PTR)-1) return 11;
    length = GetFileSize(file, 0);
    if (!length || length > sizeof(file_data)) { CloseHandle(file); return 11; }
    if (!ReadFile(file, file_data, length, &read, 0) || read != length) { CloseHandle(file); return 11; }
    CloseHandle(file);
    if (!hash_matches(file_data, length, expected)) return 12;
    certificate = CertCreateCertificateContext(1, file_data, length);
    if (!certificate) return 13;
    if (equal(argv[1], L"install")) {
        /* SYSTEM_REGISTRY_W, CURRENT_USER. The registry store is writable in Wine;
         * success is accepted only after enumeration through OpenSystemStore(ROOT).
         */
        store = CertOpenStore((const char *)(ULONG_PTR)13, 0, 0, 0x10000, L"ROOT");
        if (!store) { CertFreeCertificateContext(certificate); return 14; }
        if (!CertAddCertificateContextToStore(store, certificate, 3, 0)) {
            CertCloseStore(store, 0); CertFreeCertificateContext(certificate); return 15;
        }
        if (!CertCloseStore(store, 0)) { CertFreeCertificateContext(certificate); return 16; }
    }
    CertFreeCertificateContext(certificate);
    if (!root_contains(expected)) return 17;
    print("LOCALBOX_ROOT_OK\n");
    return 0;
}
void mainCRTStartup(void) {
    int argc;
    WCHAR **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    DWORD result = argv ? run(argc, argv) : 10;
    if (argv) LocalFree(argv);
    if (result) print("LOCALBOX_ROOT_FAILED\n");
    ExitProcess(result);
}
