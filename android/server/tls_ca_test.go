package main

import (
	"crypto/x509"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestLocalCAIsKeptAcrossIPChangesAndSignsTheLeaf(t *testing.T) {
	dir := t.TempDir()
	first, caPEM, err := localCertificate(dir, "192.168.1.20")
	if err != nil {
		t.Fatal(err)
	}
	if len(first.Certificate) != 2 {
		t.Fatalf("chain = %d certificates, want leaf + CA", len(first.Certificate))
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(caPEM) {
		t.Fatal("CA PEM does not parse")
	}
	verify := func(raw []byte, host string) {
		t.Helper()
		leaf, err := x509.ParseCertificate(raw)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = leaf.Verify(x509.VerifyOptions{Roots: pool, DNSName: host}); err != nil {
			t.Fatalf("leaf for %s does not verify with the LocalBox CA: %v", host, err)
		}
	}
	verify(first.Certificate[0], "192.168.1.20")
	verify(first.Certificate[0], "127.0.0.1")
	again, sameCA, err := localCertificate(dir, "192.168.1.20")
	if err != nil || string(again.Certificate[0]) != string(first.Certificate[0]) || string(sameCA) != string(caPEM) {
		t.Fatal("a valid leaf for the same IP must be reused")
	}
	moved, movedCA, err := localCertificate(dir, "10.0.0.5")
	if err != nil {
		t.Fatal(err)
	}
	if string(movedCA) != string(caPEM) {
		t.Fatal("a new IP must not replace the CA")
	}
	verify(moved.Certificate[0], "10.0.0.5")
}

func TestLegacySelfSignedLeafIsReplacedAndBrokenCAIsNotRegenerated(t *testing.T) {
	dir := t.TempDir()
	folder := filepath.Join(dir, "tls")
	if err := os.MkdirAll(folder, 0700); err != nil {
		t.Fatal(err)
	}
	// An older build left a leaf and no CA: copy a leaf signed by an unrelated CA.
	other := t.TempDir()
	if _, _, err := localCertificate(other, "192.168.1.20"); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"server-cert.pem", "server-key.pem"} {
		data, _ := os.ReadFile(filepath.Join(other, "tls", name))
		os.WriteFile(filepath.Join(folder, name), data, 0600)
	}
	cert, _, err := localCertificate(dir, "192.168.1.20")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(folder, "localbox-ca.pem")); err != nil {
		t.Fatal("CA was not created")
	}
	if len(cert.Certificate) != 2 {
		t.Fatal("leaf is not signed by the CA")
	}
	os.WriteFile(filepath.Join(folder, "localbox-ca-key.pem"), []byte("damaged"), 0600)
	before, _ := os.ReadFile(filepath.Join(folder, "localbox-ca.pem"))
	if _, _, err := localCertificate(dir, "192.168.1.20"); err == nil {
		t.Fatal("a damaged CA key must be an error, not a silent new CA")
	}
	after, _ := os.ReadFile(filepath.Join(folder, "localbox-ca.pem"))
	if string(before) != string(after) {
		t.Fatal("damaged CA must not be rotated")
	}
}

func TestPublicCARouteServesOnlyTheCertificate(t *testing.T) {
	engineMu.Lock()
	webCAPEM = nil
	engineMu.Unlock()
	rec := httptest.NewRecorder()
	if !servePublicCA(rec, httptest.NewRequest("GET", "/localbox-ca.crt", nil)) || rec.Code != http.StatusNotFound {
		t.Fatalf("without HTTPS the CA route must 404, got %d", rec.Code)
	}
	_, caPEM, err := localCertificate(t.TempDir(), "192.168.1.20")
	if err != nil {
		t.Fatal(err)
	}
	engineMu.Lock()
	webCAPEM = caPEM
	engineMu.Unlock()
	t.Cleanup(func() { engineMu.Lock(); webCAPEM = nil; engineMu.Unlock() })
	rec = httptest.NewRecorder()
	servePublicCA(rec, httptest.NewRequest("GET", "/localbox-ca.crt", nil))
	if rec.Code != 200 || rec.Body.String() != string(caPEM) || rec.Header().Get("Content-Disposition") == "" {
		t.Fatalf("CA route: %d %q", rec.Code, rec.Body.String()[:20])
	}
	if servePublicCA(httptest.NewRecorder(), httptest.NewRequest("GET", "/localbox-ca-key.pem", nil)) {
		t.Fatal("only the public CA paths are served")
	}
}
