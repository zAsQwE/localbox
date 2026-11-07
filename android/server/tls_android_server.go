package main

// App-private LocalBox CA and the server certificate it signs. No trust-store changes or external tools.
import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"math/big"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type webTLSOptions struct {
	Enabled bool `json:"enabled"`
	Port    int  `json:"port"`
}

func readWebTLS(directory string) (webTLSOptions, error) {
	var options webTLSOptions
	data, err := os.ReadFile(filepath.Join(directory, "web-tls.json"))
	if os.IsNotExist(err) {
		return options, nil
	}
	if err != nil {
		return options, err
	}
	if err = json.Unmarshal(data, &options); err != nil {
		return options, fmt.Errorf("настройки HTTPS: %w", err)
	}
	if options.Enabled && (options.Port < 1024 || options.Port > 65535) {
		return options, fmt.Errorf("порт HTTPS должен быть от 1024 до 65535")
	}
	return options, nil
}
// LocalBox CA, as on the desktop: created once in the app-private folder and never
// replaced automatically, so a browser or PC that trusted it keeps trusting it. Only
// the server certificate it signs is renewed (new IP, close to expiry).
func localCA(folder string) (*x509.Certificate, *ecdsa.PrivateKey, []byte, error) {
	certFile := filepath.Join(folder, "localbox-ca.pem")
	keyFile := filepath.Join(folder, "localbox-ca-key.pem")
	certPEM, certErr := os.ReadFile(certFile)
	keyPEM, keyErr := os.ReadFile(keyFile)
	if certErr == nil || keyErr == nil {
		if certErr != nil || keyErr != nil {
			return nil, nil, nil, fmt.Errorf("CA LocalBox повреждён: нет одного из файлов в %s", folder)
		}
		pair, err := tls.X509KeyPair(certPEM, keyPEM)
		if err != nil {
			return nil, nil, nil, fmt.Errorf("CA LocalBox повреждён: %w", err)
		}
		ca, err := x509.ParseCertificate(pair.Certificate[0])
		key, ok := pair.PrivateKey.(*ecdsa.PrivateKey)
		if err != nil || !ok || !ca.IsCA {
			return nil, nil, nil, fmt.Errorf("CA LocalBox повреждён")
		}
		return ca, key, certPEM, nil
	}
	if !os.IsNotExist(certErr) || !os.IsNotExist(keyErr) {
		return nil, nil, nil, fmt.Errorf("CA LocalBox: %v %v", certErr, keyErr)
	}
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, nil, nil, err
	}
	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	if err != nil {
		return nil, nil, nil, err
	}
	template := &x509.Certificate{SerialNumber: serial,
		Subject:   pkix.Name{CommonName: "LocalBox Android CA " + serial.Text(16)[:8], Organization: []string{"LocalBox"}},
		NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().AddDate(10, 0, 0),
		KeyUsage: x509.KeyUsageCertSign | x509.KeyUsageCRLSign, BasicConstraintsValid: true, IsCA: true, MaxPathLenZero: true}
	der, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		return nil, nil, nil, err
	}
	private, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		return nil, nil, nil, err
	}
	certPEM = pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	if err = os.WriteFile(keyFile, pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: private}), 0600); err != nil {
		return nil, nil, nil, err
	}
	if err = os.WriteFile(certFile, certPEM, 0600); err != nil {
		return nil, nil, nil, err
	}
	ca, err := x509.ParseCertificate(der)
	return ca, key, certPEM, err
}

// localCertificate returns the server certificate (chain: leaf + LocalBox CA) and the
// public CA in PEM. A leaf from an older build (self-signed, no CA) is replaced.
func localCertificate(directory, host string) (tls.Certificate, []byte, error) {
	folder := filepath.Join(directory, "tls")
	if err := os.MkdirAll(folder, 0700); err != nil {
		return tls.Certificate{}, nil, err
	}
	ca, caKey, caPEM, err := localCA(folder)
	if err != nil {
		return tls.Certificate{}, nil, err
	}
	certFile := filepath.Join(folder, "server-cert.pem")
	keyFile := filepath.Join(folder, "server-key.pem")
	if existing, err := tls.LoadX509KeyPair(certFile, keyFile); err == nil {
		if parsed, err := x509.ParseCertificate(existing.Certificate[0]); err == nil && parsed.VerifyHostname(host) == nil &&
			time.Until(parsed.NotAfter) > 7*24*time.Hour && parsed.CheckSignatureFrom(ca) == nil {
			existing.Certificate = [][]byte{existing.Certificate[0], ca.Raw}
			return existing, caPEM, nil
		}
	}
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return tls.Certificate{}, nil, err
	}
	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	if err != nil {
		return tls.Certificate{}, nil, err
	}
	template := &x509.Certificate{SerialNumber: serial, Subject: pkix.Name{CommonName: "LocalBox Android", Organization: []string{"LocalBox"}},
		NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().AddDate(0, 0, 397), KeyUsage: x509.KeyUsageDigitalSignature,
		ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}, BasicConstraintsValid: true, DNSNames: []string{"localhost"}, IPAddresses: []net.IP{net.ParseIP("127.0.0.1")}}
	if ip := net.ParseIP(host); ip != nil {
		template.IPAddresses = append(template.IPAddresses, ip)
	} else if host != "localhost" {
		template.DNSNames = append(template.DNSNames, host)
	}
	der, err := x509.CreateCertificate(rand.Reader, template, ca, &key.PublicKey, caKey)
	if err != nil {
		return tls.Certificate{}, nil, err
	}
	private, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		return tls.Certificate{}, nil, err
	}
	certificate := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	privatePEM := pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: private})
	if err = os.WriteFile(keyFile, privatePEM, 0600); err != nil {
		return tls.Certificate{}, nil, err
	}
	if err = os.WriteFile(certFile, certificate, 0600); err != nil {
		return tls.Certificate{}, nil, err
	}
	pair, err := tls.X509KeyPair(certificate, privatePEM)
	if err != nil {
		return tls.Certificate{}, nil, err
	}
	pair.Certificate = [][]byte{der, ca.Raw}
	return pair, caPEM, nil
}

// Public LocalBox CA of the running HTTPS listener (nil when HTTPS is off).
var webCAPEM []byte

func servePublicCA(w http.ResponseWriter, req *http.Request) bool {
	path := req.URL.Path
	if req.Method != "GET" || (path != "/localbox-ca.pem" && path != "/localbox-ca.crt") {
		return false
	}
	engineMu.Lock()
	ca := webCAPEM
	engineMu.Unlock()
	if ca == nil {
		http.NotFound(w, req)
		return true
	}
	name := "localbox-ca.pem"
	if strings.HasSuffix(path, ".crt") {
		name = "localbox-ca.crt"
	}
	w.Header().Set("Content-Type", "application/x-x509-ca-cert")
	w.Header().Set("Content-Disposition", `attachment; filename="`+name+`"`)
	w.Header().Set("Cache-Control", "no-store")
	w.Write(ca)
	return true
}
